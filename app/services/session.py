import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session as SessionModel
from app.models.user import User

SESSION_COOKIE_NAME = "session_id"
SESSION_TTL_DAYS = 30


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(db: AsyncSession, user_id: UUID) -> str:
    """Adds the session row to `db` but does not commit -- caller controls the
    transaction boundary so this can be committed atomically with other changes
    (e.g. the user/token upsert during OAuth callback)."""
    raw_token = secrets.token_urlsafe(32)
    db.add(
        SessionModel(
            id=_hash_token(raw_token),
            user_id=user_id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS),
        )
    )
    return raw_token


async def get_user_for_token(db: AsyncSession, raw_token: str) -> User | None:
    session_row = await db.get(SessionModel, _hash_token(raw_token))
    if session_row is None:
        return None
    if session_row.expires_at < datetime.now(timezone.utc):
        await db.delete(session_row)
        await db.commit()
        return None
    return await db.get(User, session_row.user_id)


async def delete_session(db: AsyncSession, raw_token: str) -> None:
    await db.execute(delete(SessionModel).where(SessionModel.id == _hash_token(raw_token)))
    await db.commit()
