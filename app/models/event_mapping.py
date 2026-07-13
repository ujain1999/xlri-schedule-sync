import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SourceType(str, enum.Enum):
    class_session = "class_session"
    activity = "activity"


class EventMapping(Base, TimestampMixin):
    """The XLRI <-> Google Calendar event diff/state table -- the core of sync."""

    __tablename__ = "event_mappings"
    __table_args__ = (
        UniqueConstraint("user_id", "source_type", "source_id", name="uq_event_mapping_source"),
        Index("ix_event_mappings_user_last_seen", "user_id", "last_seen_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType, name="source_type_enum"), nullable=False)
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    google_event_id: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    # Denormalized from the source item so stale-mapping cleanup can tell "outside the
    # current fetch window" apart from "genuinely disappeared from XLRI" without a refetch.
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
