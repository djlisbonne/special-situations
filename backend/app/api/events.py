from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from app.api.schemas import AxisScore, EventDetail, EventSummary, FilingOut
from app.db.models import Event, EventType
from app.db.session import get_db
from app.fundamentals.massive import Massive

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventSummary])
def list_events(
    db: Session = Depends(get_db),
    event_type: str | None = Query(None),
    min_score: float | None = Query(None),
    limit: int = Query(100, le=500),
):
    q = db.query(Event).options(joinedload(Event.filing))
    if event_type:
        try:
            q = q.filter(Event.event_type == EventType(event_type))
        except ValueError:
            raise HTTPException(400, f"unknown event_type: {event_type}")
    if min_score is not None:
        q = q.filter(Event.composite_score >= min_score)
    q = q.order_by(desc(Event.composite_score), desc(Event.created_at)).limit(limit)
    rows = q.all()
    out: list[EventSummary] = []
    for e in rows:
        out.append(
            EventSummary(
                id=e.id,
                event_type=e.event_type.value,
                status=e.status.value,
                parent_name=e.parent_name,
                parent_ticker=e.parent_ticker,
                spinco_name=e.spinco_name,
                spinco_ticker=e.spinco_ticker,
                distribution_ratio=e.distribution_ratio,
                record_date=e.record_date,
                distribution_date=e.distribution_date,
                headline=e.headline,
                composite_score=e.composite_score,
                filed_at=e.filing.filed_at,
                accession_number=e.filing.accession_number,
            )
        )
    return out


def _axes(rationale: dict | None) -> dict[str, AxisScore]:
    if not rationale:
        return {}
    axes = (rationale or {}).get("axes") or {}
    out: dict[str, AxisScore] = {}
    for k, v in axes.items():
        if not isinstance(v, dict):
            continue
        out[k] = AxisScore(
            score=v.get("score"),
            rationale=v.get("rationale"),
            citations=v.get("citations") or [],
        )
    return out


@router.get("/{event_id}", response_model=EventDetail)
def get_event(event_id: int, db: Session = Depends(get_db)):
    e = (
        db.query(Event)
        .options(joinedload(Event.filing))
        .filter(Event.id == event_id)
        .one_or_none()
    )
    if not e:
        raise HTTPException(404, "event not found")
    market = Massive()
    parent_snap = market.snapshot(e.parent_ticker) if e.parent_ticker else None
    spinco_snap = market.snapshot(e.spinco_ticker) if e.spinco_ticker else None
    return EventDetail(
        id=e.id,
        event_type=e.event_type.value,
        status=e.status.value,
        parent_cik=e.parent_cik,
        parent_name=e.parent_name,
        parent_ticker=e.parent_ticker,
        spinco_name=e.spinco_name,
        spinco_ticker=e.spinco_ticker,
        distribution_ratio=e.distribution_ratio,
        record_date=e.record_date,
        distribution_date=e.distribution_date,
        headline=e.headline,
        thesis=e.thesis,
        rationale_stated=e.rationale_stated,
        composite_score=e.composite_score,
        scores=_axes(e.score_rationale),
        flags=e.flags or {},
        filing=FilingOut.model_validate(e.filing),
        parent_snapshot=parent_snap,
        spinco_snapshot=spinco_snap,
    )
