from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.database import get_db
from app.deps import get_current_user_optional
from app.models.google_oauth import GoogleOAuthToken
from app.models.sync_run import SyncRun
from app.models.sync_settings import SyncSettings
from app.models.xlri_credentials import XlriCredentials

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


def _format_interval(minutes: int) -> str:
    if minutes % 1440 == 0 and minutes // 1440 == 1:
        return "once a day"
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"every {hours} hour" + ("s" if hours != 1 else "")
    return f"every {minutes} minutes"


@router.get("/")
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_optional(request, db)
    if user is None:
        return templates.TemplateResponse(
            request, "login.html", {"sync_interval_display": _format_interval(app_settings.sync_interval_minutes)}
        )

    xlri_result = await db.execute(select(XlriCredentials).where(XlriCredentials.user_id == user.id))
    oauth_result = await db.execute(select(GoogleOAuthToken).where(GoogleOAuthToken.user_id == user.id))
    settings_result = await db.execute(select(SyncSettings).where(SyncSettings.user_id == user.id))
    runs_result = await db.execute(
        select(SyncRun).where(SyncRun.user_id == user.id).order_by(SyncRun.started_at.desc()).limit(10)
    )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "xlri_creds": xlri_result.scalar_one_or_none(),
            "oauth_row": oauth_result.scalar_one_or_none(),
            "sync_settings": settings_result.scalar_one_or_none(),
            "runs": runs_result.scalars().all(),
            "sync_interval_display": _format_interval(app_settings.sync_interval_minutes),
        },
    )
