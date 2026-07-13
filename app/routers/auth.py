from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.google_oauth import GoogleOAuthToken
from app.models.sync_settings import SyncSettings
from app.models.user import User
from app.services.crypto import encrypt
from app.services.google_oauth import oauth
from app.services.session import SESSION_COOKIE_NAME, SESSION_TTL_DAYS, create_session, delete_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/google/login")
async def google_login(request: Request):
    # access_type=offline + prompt=consent are both required to get a refresh_token
    # back -- Google only issues one on the very first consent otherwise, and never
    # on subsequent logins unless consent is forced again.
    return await oauth.google.authorize_redirect(
        request, settings.google_redirect_uri, access_type="offline", prompt="consent"
    )


@router.get("/google/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo") or await oauth.google.userinfo(token=token)

    google_sub = userinfo["sub"]
    email = userinfo["email"]
    full_name = userinfo.get("name")
    avatar_url = userinfo.get("picture")

    result = await db.execute(select(User).where(User.google_sub == google_sub))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(google_sub=google_sub, email=email, full_name=full_name, avatar_url=avatar_url)
        db.add(user)
        await db.flush()
    else:
        user.email = email
        user.full_name = full_name
        user.avatar_url = avatar_url

    refresh_token = token.get("refresh_token")
    access_token = token.get("access_token")
    scopes = token.get("scope", "")
    expires_at = (
        datetime.fromtimestamp(token["expires_at"], tz=timezone.utc)
        if token.get("expires_at")
        else None
    )

    result = await db.execute(select(GoogleOAuthToken).where(GoogleOAuthToken.user_id == user.id))
    oauth_row = result.scalar_one_or_none()

    if oauth_row is None:
        if not refresh_token:
            raise RuntimeError(
                "Google did not return a refresh_token on first login -- check that "
                "access_type=offline and prompt=consent are set on the auth redirect."
            )
        db.add(
            GoogleOAuthToken(
                user_id=user.id,
                encrypted_refresh_token=encrypt(refresh_token),
                access_token_encrypted=encrypt(access_token) if access_token else None,
                access_token_expires_at=expires_at,
                scopes=scopes,
                is_connected=True,
            )
        )
        db.add(SyncSettings(user_id=user.id))
    else:
        # Google only re-issues a refresh_token when consent is re-prompted; keep the
        # existing one if this response didn't include a new one.
        if refresh_token:
            oauth_row.encrypted_refresh_token = encrypt(refresh_token)
        if access_token:
            oauth_row.access_token_encrypted = encrypt(access_token)
        oauth_row.access_token_expires_at = expires_at
        oauth_row.scopes = scopes
        oauth_row.is_connected = True

    raw_session_token = await create_session(db, user.id)
    await db.commit()

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_session_token,
        max_age=SESSION_TTL_DAYS * 24 * 3600,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )
    return response


@router.post("/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        await delete_session(db, raw_token)
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
