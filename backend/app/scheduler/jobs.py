from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.db.models import ScanRun
from app.db.session import SessionLocal
from app.events.pipeline import run_scan

log = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None


async def daily_scan():
    settings = get_settings()
    db = SessionLocal()
    run = ScanRun()
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        seen, created = await run_scan(
            db, lookback_days=settings.scan_lookback_days, scan_run_id=run.id
        )
        run.filings_seen = seen
        run.events_created = created
        run.ok = True
    except Exception as exc:
        log.exception("scan failed")
        run.ok = False
        run.error = str(exc)
    finally:
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.close()


def start_scheduler() -> None:
    global _scheduler
    if _scheduler:
        return
    settings = get_settings()
    sched = AsyncIOScheduler(timezone="UTC")
    sched.add_job(
        daily_scan,
        CronTrigger(hour=settings.scan_cron_hour, minute=settings.scan_cron_minute),
        id="daily_scan",
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    _scheduler = sched
    log.info("scheduler started; daily_scan at %02d:%02d UTC",
             settings.scan_cron_hour, settings.scan_cron_minute)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
