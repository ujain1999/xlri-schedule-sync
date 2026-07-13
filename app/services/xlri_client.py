"""Python port of the XLRI ERP client (originally legacy/functions/_utils/xlri.js),
using httpx.AsyncClient so it doesn't block the event loop when called from the
scheduler/sync engine. Same endpoints and response shapes as the JS original.
"""

import httpx

BASE_URL = "https://xlerp.xlri.ac.in"
DEFAULT_TIMEOUT = 20.0


class XlriAuthError(Exception):
    """XLRI ERP rejected the credentials/token -- bad password or a revoked session.

    Callers (the sync engine) should treat this as "the user needs to re-enter their
    password," not a transient failure to retry.
    """


class XlriError(Exception):
    """Any other XLRI ERP failure: network error, timeout, unexpected response shape.

    Callers should treat this as transient and retry on the next scheduled sync.
    """


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BASE_URL, timeout=DEFAULT_TIMEOUT)


async def login(client: httpx.AsyncClient, email: str, password: str) -> dict:
    try:
        res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    except httpx.HTTPError as exc:
        raise XlriError(f"Login request failed: {exc}") from exc

    if res.status_code in (401, 403):
        raise XlriAuthError("XLRI ERP rejected the email/password")

    try:
        data = res.json()
    except ValueError as exc:
        raise XlriError(f"Login returned non-JSON response (status {res.status_code})") from exc

    if not data.get("success"):
        # XLRI's API reports bad credentials as success=false rather than a 401 status.
        raise XlriAuthError(data.get("message") or "Login failed")

    return data["data"]


async def fetch_schedule(client: httpx.AsyncClient, token: str, start_date: str, end_date: str) -> list:
    return await _authed_get(
        client,
        "/api/v1/schedule/my-schedule/student",
        token,
        {"startDate": start_date, "endDate": end_date},
        "Failed to fetch schedule",
    )


async def fetch_class_activities(client: httpx.AsyncClient, token: str, start_date: str, end_date: str) -> list:
    return await _authed_get(
        client,
        "/api/v1/class-activities/my",
        token,
        {"startDate": start_date, "endDate": end_date},
        "Failed to fetch class activities",
    )


async def _authed_get(
    client: httpx.AsyncClient, path: str, token: str, params: dict, error_message: str
) -> list:
    try:
        res = await client.get(path, params=params, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise XlriError(f"{error_message}: {exc}") from exc

    if res.status_code in (401, 403):
        raise XlriAuthError("XLRI ERP rejected the session token")

    try:
        data = res.json()
    except ValueError as exc:
        raise XlriError(f"{error_message}: non-JSON response (status {res.status_code})") from exc

    if not data.get("success"):
        raise XlriError(data.get("message") or error_message)

    return data["data"]
