"""Google Calendar integration: dedicated per-user calendar + event CRUD.

google-api-python-client is synchronous (built on httplib2), so every call that
hits the network is wrapped in asyncio.to_thread to keep it off the event loop --
this runs inside the scheduler alongside other users' syncs.
"""

import asyncio
from datetime import datetime, timezone

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.google_oauth import GoogleOAuthToken
from app.services.crypto import decrypt, encrypt

CALENDAR_SUMMARY = "XLRI Schedule"
CALENDAR_DESCRIPTION = "Auto-synced by XLRI Schedule Sync"
BATCH_SIZE = 50


class GoogleCalendarDisconnected(Exception):
    """Google rejected the refresh token (revoked grant) -- user must re-auth."""


async def get_credentials(db: AsyncSession, oauth_row: GoogleOAuthToken) -> Credentials:
    creds = Credentials(
        token=decrypt(oauth_row.access_token_encrypted) if oauth_row.access_token_encrypted else None,
        refresh_token=decrypt(oauth_row.encrypted_refresh_token),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=oauth_row.scopes.split(),
    )

    expired = (
        oauth_row.access_token_expires_at is None
        or oauth_row.access_token_expires_at <= datetime.now(timezone.utc)
    )
    if expired:
        try:
            await asyncio.to_thread(creds.refresh, GoogleAuthRequest())
        except Exception as exc:
            oauth_row.is_connected = False
            await db.commit()
            raise GoogleCalendarDisconnected(f"Google token refresh failed: {exc}") from exc

        oauth_row.access_token_encrypted = encrypt(creds.token)
        oauth_row.access_token_expires_at = (
            creds.expiry.replace(tzinfo=timezone.utc) if creds.expiry else None
        )
        if creds.refresh_token:
            oauth_row.encrypted_refresh_token = encrypt(creds.refresh_token)
        await db.commit()

    return creds


def _build_service(creds: Credentials):
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


async def ensure_dedicated_calendar(db: AsyncSession, oauth_row: GoogleOAuthToken) -> str:
    """Returns the dedicated "XLRI Schedule" secondary calendar's ID, creating it on
    first use. All event CRUD targets this calendar, never the user's primary one."""
    if oauth_row.calendar_id:
        return oauth_row.calendar_id

    creds = await get_credentials(db, oauth_row)
    service = _build_service(creds)
    calendar = await asyncio.to_thread(
        lambda: service.calendars()
        .insert(body={"summary": CALENDAR_SUMMARY, "description": CALENDAR_DESCRIPTION})
        .execute()
    )

    oauth_row.calendar_id = calendar["id"]
    await db.commit()
    return oauth_row.calendar_id


def _event_body(item: dict) -> dict:
    return {
        "summary": item["summary"],
        "description": item.get("description", ""),
        "location": item.get("location", ""),
        "start": {"dateTime": item["start_dt"].isoformat()},
        "end": {"dateTime": item["end_dt"].isoformat()},
    }


async def create_event(db: AsyncSession, oauth_row: GoogleOAuthToken, calendar_id: str, item: dict) -> str:
    creds = await get_credentials(db, oauth_row)
    service = _build_service(creds)
    event = await asyncio.to_thread(
        lambda: service.events().insert(calendarId=calendar_id, body=_event_body(item)).execute()
    )
    return event["id"]


async def update_event(
    db: AsyncSession, oauth_row: GoogleOAuthToken, calendar_id: str, google_event_id: str, item: dict
) -> None:
    creds = await get_credentials(db, oauth_row)
    service = _build_service(creds)
    await asyncio.to_thread(
        lambda: service.events()
        .patch(calendarId=calendar_id, eventId=google_event_id, body=_event_body(item))
        .execute()
    )


async def delete_event(
    db: AsyncSession, oauth_row: GoogleOAuthToken, calendar_id: str, google_event_id: str
) -> None:
    creds = await get_credentials(db, oauth_row)
    service = _build_service(creds)

    def _delete():
        try:
            service.events().delete(calendarId=calendar_id, eventId=google_event_id).execute()
        except HttpError as exc:
            if exc.resp.status not in (404, 410):
                raise

    await asyncio.to_thread(_delete)


async def delete_calendar(db: AsyncSession, oauth_row: GoogleOAuthToken) -> None:
    """One API call to tear down the whole dedicated calendar (on disconnect), instead
    of enumerating and deleting every event in it."""
    if not oauth_row.calendar_id:
        return
    creds = await get_credentials(db, oauth_row)
    service = _build_service(creds)
    calendar_id = oauth_row.calendar_id

    def _delete():
        try:
            service.calendars().delete(calendarId=calendar_id).execute()
        except HttpError as exc:
            if exc.resp.status != 404:
                raise

    await asyncio.to_thread(_delete)
    oauth_row.calendar_id = None
    await db.commit()


async def apply_batch(
    db: AsyncSession,
    oauth_row: GoogleOAuthToken,
    calendar_id: str,
    creates: list[dict],
    updates: list[dict],
    deletes: list[str],
) -> dict:
    """Batches creates/updates/deletes into groups of BATCH_SIZE via the Calendar API's
    batch HTTP request feature -- a full sync can be 50-150 events, and we don't want
    that many sequential round-trips every 30-180 minutes per user.

    creates: [{"key": source_id, "item": normalized_item}]
    updates: [{"google_event_id": ..., "item": normalized_item}]
    deletes: [google_event_id, ...]

    Returns {"created": {key: google_event_id}, "updated": [google_event_id], "deleted":
    [google_event_id], "errors": [(op_type, key, error_str)]}.
    """
    creds = await get_credentials(db, oauth_row)
    service = _build_service(creds)

    results: dict = {"created": {}, "updated": [], "deleted": [], "errors": []}

    ops = (
        [("create", c["key"], c["item"], None) for c in creates]
        + [("update", u["google_event_id"], u["item"], u["google_event_id"]) for u in updates]
        + [("delete", d, None, d) for d in deletes]
    )

    def make_callback(op_type: str, key: str):
        def callback(request_id, response, exception):
            if exception is not None:
                if op_type == "delete" and isinstance(exception, HttpError) and exception.resp.status in (404, 410):
                    results["deleted"].append(key)
                    return
                results["errors"].append((op_type, key, str(exception)))
                return
            if op_type == "create":
                results["created"][key] = response["id"]
            elif op_type == "update":
                results["updated"].append(key)
            elif op_type == "delete":
                results["deleted"].append(key)

        return callback

    for i in range(0, len(ops), BATCH_SIZE):
        chunk = ops[i : i + BATCH_SIZE]
        batch = service.new_batch_http_request()
        for op_type, key, item, google_event_id in chunk:
            if op_type == "create":
                req = service.events().insert(calendarId=calendar_id, body=_event_body(item))
            elif op_type == "update":
                req = service.events().patch(calendarId=calendar_id, eventId=google_event_id, body=_event_body(item))
            else:
                req = service.events().delete(calendarId=calendar_id, eventId=google_event_id)
            batch.add(req, callback=make_callback(op_type, key))

        await asyncio.to_thread(batch.execute)

    return results
