from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.sync_settings import SyncSettings
from app.models.user import User
from app.models.xlri_credentials import XlriCredentials
from app.schemas.xlri_credentials import XlriCredentialsIn, XlriCredentialsOut
from app.services.crypto import encrypt
from app.services.xlri_client import XlriAuthError, XlriError, login, make_client

router = APIRouter(prefix="/api/xlri", tags=["xlri"])


@router.get("/credentials", response_model=XlriCredentialsOut | None)
async def get_credentials(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(XlriCredentials).where(XlriCredentials.user_id == user.id))
    return result.scalar_one_or_none()


@router.post("/credentials", response_model=XlriCredentialsOut)
async def submit_credentials(
    body: XlriCredentialsIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Live test login before saving anything -- matches the existing app's
    # "paste creds, get result immediately" UX, and never stores a bad password.
    async with make_client() as client:
        try:
            await login(client, body.email, body.password)
        except XlriAuthError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except XlriError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    result = await db.execute(select(XlriCredentials).where(XlriCredentials.user_id == user.id))
    row = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if row is None:
        row = XlriCredentials(
            user_id=user.id,
            xlri_email=body.email,
            encrypted_password=encrypt(body.password),
            is_verified=True,
            last_verified_at=now,
        )
        db.add(row)
    else:
        row.xlri_email = body.email
        row.encrypted_password = encrypt(body.password)
        row.is_verified = True
        row.last_verified_at = now
        row.last_error = None

    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/credentials", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credentials(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(XlriCredentials).where(XlriCredentials.user_id == user.id))
    row = result.scalar_one_or_none()
    if row is not None:
        await db.delete(row)

    # Pause sync too, so the scheduler stops picking up a user with no credentials left.
    settings_result = await db.execute(select(SyncSettings).where(SyncSettings.user_id == user.id))
    settings_row = settings_result.scalar_one_or_none()
    if settings_row is not None:
        settings_row.enabled = False

    await db.commit()
