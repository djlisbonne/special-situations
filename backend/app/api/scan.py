from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.activity import bus
from app.config import get_settings
from app.db.models import ScanRun
from app.db.session import SessionLocal, get_db
from app.events.pipeline import run_scan

log = logging.getLogger(__name__)
router = APIRouter(prefix="/scan", tags=["scan"])


async def _run_scan_task(scan_run_id: int, lookback_days: int) -> None:
    """Background task that owns its own DB session for the duration of the scan."""
    db = SessionLocal()
    try:
        seen, created = await run_scan(
            db, lookback_days=lookback_days, scan_run_id=scan_run_id
        )
        run = db.query(ScanRun).filter(ScanRun.id == scan_run_id).one_or_none()
        if run:
            run.filings_seen = seen
            run.events_created = created
            run.ok = True
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
    except Exception as exc:
        log.exception("scan task failed")
        run = db.query(ScanRun).filter(ScanRun.id == scan_run_id).one_or_none()
        if run:
            run.ok = False
            run.error = str(exc)
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


@router.post("")
async def trigger_scan(
    db: Session = Depends(get_db),
    lookback_days: int | None = Query(None, ge=1, le=180),
):
    """Kick off a scan in the background and return immediately with a run id.

    The frontend uses the run id to filter activity events for this scan and
    detect completion (via the `scan.done` activity event).
    """
    days = lookback_days or get_settings().scan_lookback_days
    run = ScanRun()
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id = run.id

    # Fire-and-forget on the main event loop.
    asyncio.create_task(_run_scan_task(run_id, days))
    bus().emit(
        "info",
        "scan.queued",
        f"Scan queued (lookback {days}d)",
        scan_run_id=run_id,
        lookback_days=days,
    )
    return {"scan_run_id": run_id, "lookback_days": days, "status": "running"}


@router.get("/{scan_run_id}")
def get_scan(scan_run_id: int, db: Session = Depends(get_db)):
    run = db.query(ScanRun).filter(ScanRun.id == scan_run_id).one_or_none()
    if not run:
        raise HTTPException(404, "scan run not found")
    finished = run.finished_at is not None
    return {
        "scan_run_id": run.id,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "finished": finished,
        "ok": run.ok,
        "error": run.error,
        "filings_seen": run.filings_seen,
        "events_created": run.events_created,
    }


@router.get("")
def list_scans(db: Session = Depends(get_db), limit: int = Query(20, ge=1, le=100)):
    rows = db.query(ScanRun).order_by(desc(ScanRun.started_at)).limit(limit).all()
    return [
        {
            "scan_run_id": r.id,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "ok": r.ok,
            "filings_seen": r.filings_seen,
            "events_created": r.events_created,
        }
        for r in rows
    ]
