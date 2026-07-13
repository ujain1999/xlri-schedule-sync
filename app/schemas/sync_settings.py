from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SyncSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    last_synced_at: datetime | None
    # Global, operator-controlled (SYNC_INTERVAL_MINUTES env var) -- informational
    # only, not accepted on SyncSettingsIn.
    sync_interval_minutes: int


class SyncSettingsIn(BaseModel):
    enabled: bool | None = None
