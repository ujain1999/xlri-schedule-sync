from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class XlriCredentialsIn(BaseModel):
    email: EmailStr
    password: str


class XlriCredentialsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    xlri_email: str
    is_verified: bool
    last_verified_at: datetime | None
    last_error: str | None
