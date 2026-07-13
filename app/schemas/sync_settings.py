from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SyncSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    sync_interval_minutes: int
    window_weeks_ahead: int
    window_days_behind: int
    last_synced_at: datetime | None


class SyncSettingsIn(BaseModel):
    enabled: bool | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=30, le=180)
    window_weeks_ahead: int | None = Field(default=None, ge=1, le=12)
    window_days_behind: int | None = Field(default=None, ge=0, le=7)
