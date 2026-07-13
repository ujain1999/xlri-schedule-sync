"""Core sync engine: fetches a user's XLRI schedule, diffs it against what's already
on their dedicated Google Calendar (via app/models/event_mapping.py), and reconciles
the difference. Called identically by the scheduler tick and the "sync now" endpoint.
"""

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.event_mapping import EventMapping, SourceType
from app.models.google_oauth import GoogleOAuthToken
from app.models.sync_run import ErrorStage, SyncRun, SyncStatus
from app.models.sync_settings import SyncSettings
from app.models.xlri_credentials import XlriCredentials
from app.services import google_calendar
from app.services.crypto import decrypt
from app.services.xlri_client import (
    XlriAuthError,
    XlriError,
    fetch_class_activities,
    fetch_schedule,
    login,
    make_client,
)

# XLRI's API returns local (India) dates/times with no timezone info.
XLRI_TZ = timezone(timedelta(hours=5, minutes=30))

# Fixed for every user, not configurable -- how far back/forward each sync fetches.
WINDOW_DAYS_BEHIND = 1
WINDOW_WEEKS_AHEAD = 4


def _parse_dt(date_str: str, time_str: str) -> datetime:
    d = date.fromisoformat(date_str)
    h, m = (int(x) for x in time_str.split(":")[:2])
    return datetime.combine(d, time(h, m), tzinfo=XLRI_TZ)


def _normalize_session(s: dict) -> dict:
    course = s["course"]
    faculty = s["faculty"]
    venue = s.get("venue")
    section = s.get("section") or {}
    faculty_name = f"{faculty.get('prefix', '')} {faculty.get('firstName', '')} {faculty.get('lastName', '')}".strip()
    description = "\n".join(
        filter(
            None,
            [
                f"Faculty: {faculty_name}" if faculty_name else None,
                f"Course Code: {course['courseCode']}",
                f"Section: {section.get('sectionName')}" if section.get("sectionName") else None,
                f"Type: {s.get('courseOfferType')}" if s.get("courseOfferType") else None,
            ],
        )
    )
    location = f"{venue['name']} ({venue['building']})" if venue else ""
    return {
        "source_type": SourceType.class_session,
        "source_id": str(s["sessionId"]),
        "summary": course["courseName"],
        "description": description,
        "location": location,
        "start_dt": _parse_dt(s["classDate"], s["startTime"]),
        "end_dt": _parse_dt(s["classDate"], s["endTime"]),
        "is_removed": bool(s.get("isCancelled")),
    }


def _normalize_activity(a: dict) -> dict:
    venue = a.get("venue")
    batch_section = a.get("batchSection")
    description = "\n".join(
        filter(
            None,
            [
                f"Type: {a.get('type')}" if a.get("type") else None,
                f"Section: {batch_section['sectionName']}" if batch_section else None,
            ],
        )
    )
    location = f"{venue['name']} ({venue['building']})" if venue else ""
    return {
        "source_type": SourceType.activity,
        "source_id": str(a["id"]),
        "summary": a["name"],
        "description": description,
        "location": location,
        "start_dt": _parse_dt(a["date"], a["startTime"]),
        "end_dt": _parse_dt(a["date"], a["endTime"]),
        "is_removed": bool(a.get("isDeleted")),
    }


def _content_hash(item: dict) -> str:
    payload = {
        "summary": item["summary"],
        "description": item["description"],
        "location": item["location"],
        "start_dt": item["start_dt"].isoformat(),
        "end_dt": item["end_dt"].isoformat(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


async def sync_user(user_id: UUID) -> None:
    """Entry point used by both the scheduler tick and the manual "sync now" trigger.
    Always writes a sync_runs row, even on unexpected failure, so problems are visible
    per-user rather than silently swallowed."""
    async with async_session() as db:
        run = SyncRun(user_id=user_id, status=SyncStatus.running)
        db.add(run)
        await db.commit()
        await db.refresh(run)

        try:
            await _do_sync(db, user_id, run)
        except Exception as exc:
            run.status = SyncStatus.failed
            run.error_stage = ErrorStage.internal
            run.error_message = str(exc)
        finally:
            run.finished_at = datetime.now(timezone.utc)
            await db.commit()


async def _do_sync(db: AsyncSession, user_id: UUID, run: SyncRun) -> None:
    creds_result = await db.execute(select(XlriCredentials).where(XlriCredentials.user_id == user_id))
    xlri_creds = creds_result.scalar_one_or_none()
    if xlri_creds is None:
        run.status = SyncStatus.failed
        run.error_stage = ErrorStage.xlri_login
        run.error_message = "No XLRI credentials on file"
        return

    settings_result = await db.execute(select(SyncSettings).where(SyncSettings.user_id == user_id))
    sync_settings = settings_result.scalar_one_or_none()
    if sync_settings is None or not sync_settings.enabled:
        run.status = SyncStatus.failed
        run.error_stage = ErrorStage.internal
        run.error_message = "Sync disabled"
        return

    oauth_result = await db.execute(select(GoogleOAuthToken).where(GoogleOAuthToken.user_id == user_id))
    oauth_row = oauth_result.scalar_one_or_none()
    if oauth_row is None or not oauth_row.is_connected:
        run.status = SyncStatus.failed
        run.error_stage = ErrorStage.google_api
        run.error_message = "Google Calendar not connected"
        return

    password = decrypt(xlri_creds.encrypted_password)
    window_start = date.today() - timedelta(days=WINDOW_DAYS_BEHIND)
    window_end = date.today() + timedelta(weeks=WINDOW_WEEKS_AHEAD)

    async with make_client() as client:
        try:
            auth_data = await login(client, xlri_creds.xlri_email, password)
        except XlriAuthError as exc:
            xlri_creds.is_verified = False
            xlri_creds.last_error = str(exc)
            run.status = SyncStatus.failed
            run.error_stage = ErrorStage.xlri_login
            run.error_message = str(exc)
            return
        except XlriError as exc:
            # Transient (network/timeout/5xx) -- leave is_verified alone, next tick retries.
            run.status = SyncStatus.failed
            run.error_stage = ErrorStage.xlri_login
            run.error_message = str(exc)
            return

        token = auth_data["token"]

        try:
            sessions = await fetch_schedule(client, token, window_start.isoformat(), window_end.isoformat())
            activities = await fetch_class_activities(
                client, token, window_start.isoformat(), window_end.isoformat()
            )
        except (XlriAuthError, XlriError) as exc:
            run.status = SyncStatus.failed
            run.error_stage = ErrorStage.xlri_fetch
            run.error_message = str(exc)
            return

    xlri_creds.is_verified = True
    xlri_creds.last_verified_at = datetime.now(timezone.utc)
    xlri_creds.last_error = None

    normalized = [_normalize_session(s) for s in sessions] + [_normalize_activity(a) for a in activities]

    try:
        calendar_id = await google_calendar.ensure_dedicated_calendar(db, oauth_row)
    except google_calendar.GoogleCalendarDisconnected as exc:
        run.status = SyncStatus.failed
        run.error_stage = ErrorStage.google_api
        run.error_message = str(exc)
        return

    mapping_result = await db.execute(select(EventMapping).where(EventMapping.user_id == user_id))
    existing_mappings = {(m.source_type, m.source_id): m for m in mapping_result.scalars().all()}

    now = datetime.now(timezone.utc)
    processed_keys: set[tuple[SourceType, str]] = set()
    creates, updates, deletes = [], [], []

    for item in normalized:
        key = (item["source_type"], item["source_id"])
        mapping = existing_mappings.get(key)
        processed_keys.add(key)

        if item["is_removed"]:
            if mapping is not None:
                deletes.append(mapping)
            continue

        content_hash = _content_hash(item)
        if mapping is None:
            creates.append({"key": key, "item": item, "content_hash": content_hash})
        elif mapping.content_hash != content_hash:
            updates.append({"key": key, "mapping": mapping, "item": item, "content_hash": content_hash})
        else:
            mapping.last_seen_at = now

    # Anything that existed before, falls inside this run's fetch window, but wasn't
    # returned by XLRI at all this time (not even as cancelled) -- treat as gone. The
    # window check stops us from deleting mappings for events simply beyond this run's
    # fetch horizon.
    for key, mapping in existing_mappings.items():
        if key in processed_keys:
            continue
        if window_start <= mapping.start_at.date() <= window_end:
            deletes.append(mapping)

    batch_creates = [{"key": c["key"], "item": c["item"]} for c in creates]
    batch_updates = [
        {"google_event_id": u["mapping"].google_event_id, "item": u["item"], "key": u["key"]} for u in updates
    ]
    batch_deletes = [m.google_event_id for m in deletes]

    try:
        result = await google_calendar.apply_batch(
            db, oauth_row, calendar_id, batch_creates, batch_updates, batch_deletes
        )
    except google_calendar.GoogleCalendarDisconnected as exc:
        run.status = SyncStatus.failed
        run.error_stage = ErrorStage.google_api
        run.error_message = str(exc)
        return

    created_by_key = {c["key"]: c for c in creates}
    for key, google_event_id in result["created"].items():
        c = created_by_key[key]
        db.add(
            EventMapping(
                user_id=user_id,
                source_type=key[0],
                source_id=key[1],
                google_event_id=google_event_id,
                content_hash=c["content_hash"],
                start_at=c["item"]["start_dt"],
                last_seen_at=now,
            )
        )

    updated_by_event_id = {u["mapping"].google_event_id: u for u in updates}
    for google_event_id in result["updated"]:
        u = updated_by_event_id[google_event_id]
        u["mapping"].content_hash = u["content_hash"]
        u["mapping"].start_at = u["item"]["start_dt"]
        u["mapping"].last_seen_at = now

    deleted_by_event_id = {m.google_event_id: m for m in deletes}
    for google_event_id in result["deleted"]:
        m = deleted_by_event_id.get(google_event_id)
        if m is not None:
            await db.delete(m)

    run.events_created = len(result["created"])
    run.events_updated = len(result["updated"])
    run.events_deleted = len(result["deleted"])

    if result["errors"]:
        run.status = SyncStatus.partial_failure
        run.error_stage = ErrorStage.google_api
        run.error_message = "; ".join(f"{op} {key}: {err}" for op, key, err in result["errors"][:5])
    else:
        run.status = SyncStatus.success

    sync_settings.last_synced_at = now
