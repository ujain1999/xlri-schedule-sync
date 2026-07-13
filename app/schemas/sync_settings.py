from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SyncSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    window_weeks_ahead: int
    window_days_behind: int
    last_synced_at: datetime | None
    # Global, operator-controlled (SYNC_INTERVAL_MINUTES env var) -- informational
    # only, not accepted on SyncSettingsIn.
    sync_interval_minutes: int


class SyncSettingsIn(BaseModel):
    enabled: bool | None = None
    window_weeks_ahead: int | None = Field(default=None, ge=1, le=12)
    window_days_behind: int | None = Field(default=None, ge=0, le=7)
