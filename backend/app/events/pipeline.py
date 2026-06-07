"""End-to-end pipeline: filing -> persisted Event with extraction and scoring.

All stages emit to the activity bus so the frontend's ActivityPanel can show
the user exactly where the pipeline is. Synchronous OpenAI calls are routed
through asyncio.to_thread so the event loop stays free to flush SSE messages
while the LLM is thinking.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.activity import bus
from app.db.models import Event, EventStatus, EventType, Filing
from app.edgar.client import EdgarClient, FilingRef, SPINOFF_FORMS
from app.edgar.parsers import html_to_text
from app.events.detector import classify_by_form
from app.events.spinoff import extract_spinoff_fields, score_spinoff

log = logging.getLogger(__name__)


def _save_filing(db: Session, ref: FilingRef, text: str) -> Filing:
    f = db.query(Filing).filter(Filing.accession_number == ref.accession_number).one_or_none()
    if f:
        if not f.raw_text:
            f.raw_text = text
            f.fetched_at = datetime.now(timezone.utc)
            db.commit()
        return f
    f = Filing(
        accession_number=ref.accession_number,
        cik=ref.cik,
        company_name=ref.company_name,
        form_type=ref.form_type,
        filed_at=ref.filed_at,
        primary_doc_url=ref.primary_doc_url,
        index_url=ref.index_url,
        raw_text=text,
        fetched_at=datetime.now(timezone.utc),
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


def _existing_event_for_filing(db: Session, filing_id: int) -> Event | None:
    return db.query(Event).filter(Event.filing_id == filing_id).first()


async def analyze_spinoff_filing(
    db: Session, filing: Filing, *, scan_run_id: int | None = None
) -> Event:
    text = filing.raw_text or ""

    bus().emit(
        "info",
        "llm.extract",
        f"Extracting fields from {filing.company_name} ({filing.form_type})",
        scan_run_id=scan_run_id,
        accession=filing.accession_number,
        chars=len(text),
    )
    extracted = await asyncio.to_thread(extract_spinoff_fields, text)

    bus().emit(
        "info",
        "llm.score",
        f"Scoring {extracted.get('spinco_name') or filing.company_name} on Greenblatt axes",
        scan_run_id=scan_run_id,
        accession=filing.accession_number,
        spinco_name=extracted.get("spinco_name"),
    )
    scored = await asyncio.to_thread(score_spinoff, text, extracted)

    axes = scored.get("axes", {})

    def axis_score(name: str) -> float | None:
        v = axes.get(name, {})
        try:
            return float(v.get("score")) if v.get("score") is not None else None
        except (TypeError, ValueError):
            return None

    event = _existing_event_for_filing(db, filing.id)
    if not event:
        event = Event(filing_id=filing.id, event_type=EventType.SPINOFF)
        db.add(event)

    event.status = EventStatus.ANNOUNCED
    event.parent_cik = filing.cik
    event.parent_name = extracted.get("parent_name") or filing.company_name
    event.parent_ticker = extracted.get("parent_ticker")
    event.spinco_name = extracted.get("spinco_name")
    event.spinco_ticker = extracted.get("expected_ticker_listing")
    event.distribution_ratio = extracted.get("distribution_ratio")
    event.record_date = extracted.get("_record_date_dt")
    event.distribution_date = extracted.get("_distribution_date_dt")
    event.expected_ticker_listing = extracted.get("expected_ticker_listing")

    event.headline = scored.get("headline")
    event.thesis = scored.get("thesis")
    event.rationale_stated = extracted.get("stated_rationale")

    event.score_insider_alignment = axis_score("insider_alignment")
    event.score_forced_selling = axis_score("forced_selling")
    event.score_hidden_value = axis_score("hidden_value")
    event.score_leverage_profile = axis_score("leverage_profile")
    event.score_information_asymmetry = axis_score("information_asymmetry")
    try:
        event.composite_score = float(scored.get("composite_score"))
    except (TypeError, ValueError):
        event.composite_score = None

    event.score_rationale = {
        "axes": axes,
        "extracted": {k: v for k, v in extracted.items() if not k.startswith("_")},
    }
    event.flags = scored.get("flags") or {}

    db.commit()
    db.refresh(event)

    bus().emit(
        "success",
        "event.created",
        f"{event.spinco_name or filing.company_name} → composite "
        f"{event.composite_score:.1f}"
        if event.composite_score is not None
        else f"{event.spinco_name or filing.company_name} → analyzed",
        scan_run_id=scan_run_id,
        event_id=event.id,
        accession=filing.accession_number,
        composite_score=event.composite_score,
        headline=event.headline,
    )
    return event


async def run_scan(
    db: Session, lookback_days: int, *, scan_run_id: int | None = None
) -> tuple[int, int]:
    filings_seen = 0
    events_created = 0

    bus().emit(
        "info",
        "scan.start",
        f"Scan starting (lookback {lookback_days} days)",
        scan_run_id=scan_run_id,
        lookback_days=lookback_days,
    )

    try:
        async with EdgarClient() as edgar:
            bus().emit(
                "info",
                "edgar.search",
                f"Querying EDGAR for {', '.join(SPINOFF_FORMS)} (last {lookback_days}d)",
                scan_run_id=scan_run_id,
            )
            refs = await edgar.recent_filings_by_form(
                SPINOFF_FORMS, lookback_days=lookback_days
            )
            bus().emit(
                "info",
                "edgar.found",
                f"Found {len(refs)} candidate filing(s)",
                scan_run_id=scan_run_id,
                count=len(refs),
            )

            for i, ref in enumerate(refs, 1):
                filings_seen += 1
                event_type = classify_by_form(ref.form_type)
                if event_type is not EventType.SPINOFF:
                    bus().emit(
                        "info",
                        "classify.skip",
                        f"Skipping non-spinoff form {ref.form_type} ({ref.company_name})",
                        scan_run_id=scan_run_id,
                    )
                    continue

                bus().emit(
                    "info",
                    "edgar.fetch",
                    f"[{i}/{len(refs)}] Fetching {ref.company_name} {ref.form_type}",
                    scan_run_id=scan_run_id,
                    accession=ref.accession_number,
                    url=ref.primary_doc_url,
                )
                try:
                    html = await edgar.fetch_document(ref.primary_doc_url)
                except Exception as exc:
                    bus().emit(
                        "error",
                        "edgar.fetch.fail",
                        f"Fetch failed: {exc}",
                        scan_run_id=scan_run_id,
                        accession=ref.accession_number,
                    )
                    continue

                text = html_to_text(html)
                filing = _save_filing(db, ref, text)
                bus().emit(
                    "info",
                    "db.save",
                    f"Saved filing ({len(text):,} chars)",
                    scan_run_id=scan_run_id,
                    accession=ref.accession_number,
                    chars=len(text),
                    filing_id=filing.id,
                )

                if _existing_event_for_filing(db, filing.id):
                    bus().emit(
                        "info",
                        "event.exists",
                        f"Already analyzed: {ref.company_name}",
                        scan_run_id=scan_run_id,
                        filing_id=filing.id,
                    )
                    continue

                try:
                    await analyze_spinoff_filing(db, filing, scan_run_id=scan_run_id)
                    events_created += 1
                except Exception as exc:
                    log.exception("analysis failed for %s", ref.accession_number)
                    bus().emit(
                        "error",
                        "llm.fail",
                        f"Analysis failed for {ref.company_name}: {exc}",
                        scan_run_id=scan_run_id,
                        accession=ref.accession_number,
                    )

        bus().emit(
            "success",
            "scan.done",
            f"Scan complete: {filings_seen} filing(s) seen, {events_created} event(s) created",
            scan_run_id=scan_run_id,
            filings_seen=filings_seen,
            events_created=events_created,
        )
    except Exception as exc:
        log.exception("scan failed")
        bus().emit(
            "error",
            "scan.fail",
            f"Scan failed: {exc}",
            scan_run_id=scan_run_id,
        )
        raise
    return filings_seen, events_created
