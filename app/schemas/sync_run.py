from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    started_at: datetime
    finished_at: datetime | None
    status: str
    events_created: int
    events_updated: int
    events_deleted: int
    error_message: str | None
    error_stage: str | None
