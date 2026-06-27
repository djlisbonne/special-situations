"""Outcome-tracking endpoints: how a spin-off actually performed vs. the thesis.

  GET /events/{id}/performance     factual report + LLM corroboration (cached)
  POST /events/{id}/performance/refresh   force a recompute (prices + LLM)
  GET  /performance/track-record   portfolio-level calibration: does the score
                                   predict realized alpha?
  POST /performance/refresh-all    recompute snapshots for every priced event
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from app.db.models import Event, EventStatus, OutcomeSnapshot
from app.db.session import get_db
from app.fundamentals.tickers import resolve_ticker
from app.performance.corroborate import corroborate
from app.performance.tracker import build_report

router = APIRouter(tags=["performance"])

# How long a cached snapshot is considered fresh. Prices move during the day but
# the thesis-vs-outcome story doesn't change minute to minute, and recomputing
# means an LLM call, so half a day is a sane default.
SNAPSHOT_TTL = timedelta(hours=12)


def _is_stale(snap: OutcomeSnapshot) -> bool:
    if snap.computed_at is None:
        return True
    computed = snap.computed_at
    if computed.tzinfo is None:
        computed = computed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - computed) > SNAPSHOT_TTL


def _compute_and_store(
    db: Session, event: Event, *, run_llm: bool = True
) -> OutcomeSnapshot:
    report = build_report(event)
    _refresh_status(event, report)
    corro = corroborate(event, report) if run_llm else None
    snap = (
        db.query(OutcomeSnapshot)
        .filter(OutcomeSnapshot.event_id == event.id)
        .one_or_none()
    )
    if snap is None:
        snap = OutcomeSnapshot(event_id=event.id)
        db.add(snap)
    snap.computed_at = datetime.now(timezone.utc)
    snap.as_of = report.get("as_of")
    snap.phase = report.get("phase")
    snap.report = report
    # Don't clobber a good prior corroboration with a None from a failed/skipped
    # LLM call — keep the last useful verdict.
    if corro is not None:
        snap.corroboration = corro
    db.commit()
    db.refresh(snap)
    return snap


def _load_event(event_id: int, db: Session) -> Event:
    e = (
        db.query(Event)
        .options(joinedload(Event.filing))
        .filter(Event.id == event_id)
        .one_or_none()
    )
    if not e:
        raise HTTPException(404, "event not found")
    return e


@router.post("/performance/resolve-tickers")
def resolve_tickers(db: Session = Depends(get_db), overwrite: bool = Query(False)):
    """Backfill missing parent tickers by name via SEC's official mapping.

    The outcome loop is dead without a ticker, and most events arrive with the
    parent named but un-tickered. We never guess: only an exact normalized-name
    match is written.
    """
    q = db.query(Event).filter(Event.parent_name.isnot(None))
    if not overwrite:
        q = q.filter(Event.parent_ticker.is_(None))
    resolved = 0
    out: list[dict] = []
    for e in q.all():
        t = resolve_ticker(e.parent_name)
        if t and t != e.parent_ticker:
            e.parent_ticker = t
            resolved += 1
            out.append({"event_id": e.id, "parent_name": e.parent_name, "ticker": t})
    db.commit()
    return {"resolved": resolved, "matches": out}


def _refresh_status(event: Event, report: dict) -> None:
    """Advance event status from the realized phase so the pipeline reflects life.

    Spin-offs land in the DB as 'announced' and never move. Once the spin-co is
    actually trading, the deal is effective; mark it so a fund can filter the
    pipeline by what's live vs. pending.
    """
    phase = report.get("phase")
    if phase in ("seasoning", "seasoned") and event.status == EventStatus.ANNOUNCED:
        event.status = EventStatus.EFFECTIVE


@router.get("/events/{event_id}/performance")
def get_performance(
    event_id: int,
    db: Session = Depends(get_db),
    refresh: bool = Query(False),
):
    e = _load_event(event_id, db)
    snap = (
        db.query(OutcomeSnapshot)
        .filter(OutcomeSnapshot.event_id == event_id)
        .one_or_none()
    )
    if refresh or snap is None or _is_stale(snap):
        snap = _compute_and_store(db, e, run_llm=True)
    return {
        "event_id": event_id,
        "computed_at": snap.computed_at,
        "report": snap.report,
        "corroboration": snap.corroboration,
    }


@router.post("/events/{event_id}/performance/refresh")
def refresh_performance(event_id: int, db: Session = Depends(get_db)):
    e = _load_event(event_id, db)
    snap = _compute_and_store(db, e, run_llm=True)
    return {
        "event_id": event_id,
        "computed_at": snap.computed_at,
        "report": snap.report,
        "corroboration": snap.corroboration,
    }


@router.post("/performance/refresh-all")
def refresh_all(
    db: Session = Depends(get_db),
    run_llm: bool = Query(True),
    limit: int = Query(200, le=500),
):
    """Recompute snapshots for every event that has a resolvable ticker.

    Used to seed the track-record page. `run_llm=false` does the cheap
    prices-only pass when you just want fresh numbers.
    """
    events = (
        db.query(Event)
        .options(joinedload(Event.filing))
        .filter((Event.parent_ticker.isnot(None)) | (Event.spinco_ticker.isnot(None)))
        .limit(limit)
        .all()
    )
    done, with_data = 0, 0
    for e in events:
        snap = _compute_and_store(db, e, run_llm=run_llm)
        done += 1
        if snap.report and snap.report.get("has_data"):
            with_data += 1
    return {"events_processed": done, "events_with_price_data": with_data}


def _headline_row(e: Event, snap: OutcomeSnapshot) -> dict | None:
    report = snap.report or {}
    h = report.get("headline")
    return {
        "event_id": e.id,
        "parent_name": e.parent_name,
        "parent_ticker": e.parent_ticker,
        "spinco_name": e.spinco_name,
        "spinco_ticker": e.spinco_ticker,
        "composite_score": e.composite_score,
        "phase": report.get("phase"),
        "phase_label": report.get("phase_label"),
        "as_of": report.get("as_of"),
        "headline": h,  # {subject, window, return, market_alpha, sector_alpha}
        "verdict": (snap.corroboration or {}).get("verdict"),
        "computed_at": snap.computed_at,
    }


@router.get("/performance/track-record")
def track_record(db: Session = Depends(get_db)):
    """Portfolio-level scorecard: every event with a cached outcome, plus a
    calibration read on whether composite score predicts realized alpha."""
    rows = (
        db.query(Event, OutcomeSnapshot)
        .join(OutcomeSnapshot, OutcomeSnapshot.event_id == Event.id)
        .options(joinedload(Event.filing))
        .order_by(desc(Event.composite_score))
        .all()
    )
    items: list[dict] = []
    for e, snap in rows:
        row = _headline_row(e, snap)
        if row and (snap.report or {}).get("has_data"):
            items.append(row)

    # Calibration: among events with a measurable headline alpha, do higher
    # scores correspond to higher market alpha? Report the simple split a fund
    # would eyeball — average alpha for top-half vs bottom-half scores.
    measurable = [
        it
        for it in items
        if it["headline"] and isinstance(it["headline"].get("market_alpha"), (int, float))
        and isinstance(it["composite_score"], (int, float))
    ]
    calibration = _calibration(measurable)

    return {"items": items, "calibration": calibration, "count": len(items)}


def _calibration(rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    alphas = [r["headline"]["market_alpha"] for r in rows]
    avg_alpha = sum(alphas) / n
    hit_rate = sum(1 for a in alphas if a > 0) / n
    summary = {
        "n": n,
        "avg_market_alpha": avg_alpha,
        "positive_alpha_rate": hit_rate,
    }
    if n >= 4:
        ordered = sorted(rows, key=lambda r: r["composite_score"])
        half = n // 2
        bottom = ordered[:half]
        top = ordered[n - half:]
        summary["bottom_half_avg_alpha"] = sum(
            r["headline"]["market_alpha"] for r in bottom
        ) / len(bottom)
        summary["top_half_avg_alpha"] = sum(
            r["headline"]["market_alpha"] for r in top
        ) / len(top)
        summary["spread"] = summary["top_half_avg_alpha"] - summary["bottom_half_avg_alpha"]
    return summary
