from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from app.api.schemas import AxisScore, EventDetail, EventSummary, FilingOut
from app.db.models import Event, EventType
from app.db.session import get_db
from app.edgar.client import EDGAR_BASE, EdgarClient
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
        positive = v.get("positive_evidence") or []
        negative = v.get("negative_evidence") or []
        out[k] = AxisScore(
            score=v.get("score"),
            rationale=v.get("rationale"),
            citations=v.get("citations") or [*positive, *negative],
            positive_evidence=positive,
            negative_evidence=negative,
            confidence=v.get("confidence"),
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


def _accession_no_dashes(accession: str) -> str:
    return accession.replace("-", "")


async def _resolve_filing_url(filing) -> str:
    """Return a URL that points at the actual primary document.

    Older filings in the DB sometimes have `primary_doc_url` pointing at the
    folder (trailing slash) because EFTS returned an empty `primary_doc`. In
    that case we look up the filing's index.json and pick the primary HTML.
    """
    url = filing.primary_doc_url
    if url and not url.endswith("/"):
        return url
    async with EdgarClient() as edgar:
        primary = await edgar.resolve_primary_doc(
            filing.cik, _accession_no_dashes(filing.accession_number)
        )
    if not primary:
        raise HTTPException(502, "could not resolve primary document on EDGAR")
    return (
        f"{EDGAR_BASE}/Archives/edgar/data/{filing.cik.lstrip('0')}/"
        f"{_accession_no_dashes(filing.accession_number)}/{primary}"
    )


_CONTENT_TYPES = {
    ".htm": "text/html; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
}


@router.get("/{event_id}/document")
async def get_event_document(event_id: int, db: Session = Depends(get_db)):
    """Stream the filing's primary document so the frontend can iframe it.

    EDGAR doesn't set CORS for our origin, so a same-origin proxy is the
    cleanest path. We also rewrite the stored URL if we had to repair it.
    """
    e = (
        db.query(Event)
        .options(joinedload(Event.filing))
        .filter(Event.id == event_id)
        .one_or_none()
    )
    if not e:
        raise HTTPException(404, "event not found")
    url = await _resolve_filing_url(e.filing)
    if url != e.filing.primary_doc_url:
        e.filing.primary_doc_url = url
        db.commit()

    async with EdgarClient() as edgar:
        r = await edgar._get(url)
    ext = re.search(r"(\.[a-zA-Z0-9]+)(?:\?|$)", url)
    media_type = _CONTENT_TYPES.get(
        ext.group(1).lower() if ext else "",
        r.headers.get("content-type", "application/octet-stream"),
    )
    content = r.content
    if media_type.startswith("text/html"):
        # Inject a <base> so relative URLs (images, exhibits) resolve back to
        # the SEC archive folder rather than to our proxy origin.
        base_href = url.rsplit("/", 1)[0] + "/"
        injection = f'<base href="{base_href}">'.encode()
        text = r.text
        lower = text.lower()
        head_idx = lower.find("<head")
        if head_idx >= 0:
            end = text.find(">", head_idx)
            if end >= 0:
                content = (
                    text[: end + 1].encode("utf-8", "ignore")
                    + injection
                    + text[end + 1 :].encode("utf-8", "ignore")
                )
        else:
            content = injection + content
    return Response(content=content, media_type=media_type)


@router.post("/{event_id}/reanalyze", response_model=EventDetail)
async def reanalyze_event(event_id: int, db: Session = Depends(get_db)):
    """Re-fetch the primary doc (repairing the URL if needed) and re-run the LLM.

    Useful after the EDGAR client gained the index.json fallback: an event whose
    `raw_text` was just a directory listing can be rescued without a full scan.
    """
    from app.edgar.parsers import html_to_text
    from app.events.pipeline import analyze_spinoff_filing

    e = (
        db.query(Event)
        .options(joinedload(Event.filing))
        .filter(Event.id == event_id)
        .one_or_none()
    )
    if not e:
        raise HTTPException(404, "event not found")
    url = await _resolve_filing_url(e.filing)
    async with EdgarClient() as edgar:
        html = await edgar.fetch_document(url)
    e.filing.primary_doc_url = url
    e.filing.raw_text = html_to_text(html)
    db.commit()
    await analyze_spinoff_filing(db, e.filing)
    return get_event(event_id, db)
