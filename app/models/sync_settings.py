import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SyncSettings(Base):
    __tablename__ = "sync_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Bounded [30, 180] in the API layer (Pydantic schema), not enforced at the DB level.
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=45, nullable=False)
    window_weeks_ahead: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    window_days_behind: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # Drives the scheduler's "who's due" query each tick.
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
