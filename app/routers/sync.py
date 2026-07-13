import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.database import get_db
from app.deps import get_current_user
from app.models.sync_run import SyncRun, SyncStatus
from app.models.sync_settings import SyncSettings
from app.models.user import User
from app.schemas.sync_run import SyncRunOut
from app.schemas.sync_settings import SyncSettingsIn, SyncSettingsOut
from app.services.sync import sync_user

router = APIRouter(prefix="/api/sync", tags=["sync"])

# Keep strong references to fire-and-forget sync tasks so asyncio doesn't garbage
# collect them mid-run -- sync_user itself already records its own result to
# sync_runs, this is purely about keeping the task object alive.
_background_tasks: set[asyncio.Task] = set()


def _fire_and_forget(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _to_out(row: SyncSettings) -> SyncSettingsOut:
    return SyncSettingsOut(
        enabled=row.enabled,
        window_weeks_ahead=row.window_weeks_ahead,
        window_days_behind=row.window_days_behind,
        last_synced_at=row.last_synced_at,
        sync_interval_minutes=app_settings.sync_interval_minutes,
    )


@router.get("/settings", response_model=SyncSettingsOut)
async def get_settings(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SyncSettings).where(SyncSettings.user_id == user.id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Sync settings not found -- log in with Google first")
    return _to_out(row)


@router.put("/settings", response_model=SyncSettingsOut)
async def update_settings(
    body: SyncSettingsIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(SyncSettings).where(SyncSettings.user_id == user.id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Sync settings not found -- log in with Google first")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)

    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.post("/now", status_code=status.HTTP_202_ACCEPTED)
async def sync_now(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SyncRun).where(SyncRun.user_id == user.id, SyncRun.status == SyncStatus.running).limit(1)
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A sync is already running")

    _fire_and_forget(sync_user(user.id))
    return {"detail": "Sync started"}


@router.get("/runs", response_model=list[SyncRunOut])
async def list_runs(
    limit: int = 20,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    limit = min(max(limit, 1), 100)
    result = await db.execute(
        select(SyncRun)
        .where(SyncRun.user_id == user.id)
        .order_by(SyncRun.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


@router.get("/runs/{run_id}", response_model=SyncRunOut)
async def get_run(run_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SyncRun).where(SyncRun.id == run_id, SyncRun.user_id == user.id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return row
