import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SyncStatus(str, enum.Enum):
    running = "running"
    success = "success"
    partial_failure = "partial_failure"
    failed = "failed"


class ErrorStage(str, enum.Enum):
    xlri_login = "xlri_login"
    xlri_fetch = "xlri_fetch"
    google_api = "google_api"
    internal = "internal"


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus, name="sync_status_enum"), nullable=False, default=SyncStatus.running
    )
    events_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    events_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    events_deleted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_stage: Mapped[ErrorStage | None] = mapped_column(
        Enum(ErrorStage, name="error_stage_enum"), nullable=True
    )
