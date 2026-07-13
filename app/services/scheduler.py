"""In-process scheduler: one recurring "tick" job (not one APScheduler job per user)
that recomputes who's due from Postgres state each time it fires. This means the
schedule survives container restarts for free -- there's no job store to persist,
"who's due" is just a query.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models.sync_settings import SyncSettings
from app.services.sync import sync_user

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def get_due_user_ids() -> list:
    async with async_session() as db:
        result = await db.execute(select(SyncSettings).where(SyncSettings.enabled.is_(True)))
        now = datetime.now(timezone.utc)
        due = []
        for row in result.scalars().all():
            if row.last_synced_at is None:
                due.append(row.user_id)
                continue
            next_due_at = row.last_synced_at + timedelta(minutes=row.sync_interval_minutes)
            if next_due_at <= now:
                due.append(row.user_id)
        return due


async def scheduler_tick() -> None:
    due_user_ids = await get_due_user_ids()
    if not due_user_ids:
        return

    logger.info("scheduler tick: %d user(s) due for sync", len(due_user_ids))
    sem = asyncio.Semaphore(settings.scheduler_max_concurrent_syncs)

    async def bounded(user_id):
        async with sem:
            try:
                await sync_user(user_id)
            except Exception:
                # sync_user already catches and records its own failures in sync_runs;
                # this is a last-resort guard so one user's bug can never take down
                # the tick for everyone else.
                logger.exception("sync_user(%s) raised unexpectedly", user_id)

    await asyncio.gather(*(bounded(uid) for uid in due_user_ids), return_exceptions=True)


def start_scheduler() -> None:
    scheduler.add_job(
        scheduler_tick,
        "interval",
        seconds=settings.scheduler_tick_seconds,
        id="scheduler_tick",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()


def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)
