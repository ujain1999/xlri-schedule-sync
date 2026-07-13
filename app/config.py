from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    encryption_key: str
    session_secret: str

    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str

    base_url: str = "http://localhost:8000"

    # Global sync cadence for every user -- not per-user configurable, so one
    # operator-controlled knob decides load on XLRI's ERP and the Google API.
    sync_interval_minutes: int = 60
    scheduler_tick_seconds: int = 300
    scheduler_max_concurrent_syncs: int = 3


settings = Settings()
