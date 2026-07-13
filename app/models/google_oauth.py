import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GoogleOAuthToken(Base):
    __tablename__ = "google_oauth_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The dedicated "XLRI Schedule" secondary calendar's Google ID -- set after first creation.
    calendar_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scopes: Mapped[str] = mapped_column(Text, nullable=False)
    # Flips false on a 401/invalid_grant from Google (user revoked access) -- surfaced in the UI.
    is_connected: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
