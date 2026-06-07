"""End-to-end pipeline: filing -> persisted Event with extraction and scoring.

All stages emit to the activity bus so the frontend's ActivityPanel can show
the user exactly where the pipeline is. Synchronous OpenAI calls are routed
through asyncio.to_thread so the event loop stays free to flush SSE messages
while the LLM is thinking.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.activity import bus
from app.db.models import Event, EventStatus, EventType, Filing
from app.edgar.client import EDGAR_BASE, EdgarClient, FilingRef, SPINOFF_FORMS
from app.edgar.parsers import html_to_text
from app.events.detector import classify_by_form
from app.events.spinoff import AXIS_WEIGHTS, extract_spinoff_fields, score_spinoff

# Per-doc and total caps for the stitched LLM context. The information statement
# (ex99-1) on a real 10-12B is typically 1-5 MB of HTML; once stripped to text
# we want enough to cover business description, capitalization, pro-formas,
# and risk factors without blowing past the model's effective window.
_PRIMARY_DOC_MAX_CHARS = 60_000
_INFO_STATEMENT_MAX_CHARS = 400_000
_SEPARATION_DOC_MAX_CHARS = 120_000
_TOTAL_FILING_MAX_CHARS = 600_000

log = logging.getLogger(__name__)


_TICKER_RE = re.compile(r"^[A-Z][A-Z.\-]{0,7}$")


def _trunc(v: object, n: int) -> str | None:
    """Coerce to str and clip to a column-friendly length.

    Several Event columns are VARCHAR-bounded (distribution_ratio 64,
    headline 512, name fields 256). The LLM is allowed to be verbose; we just
    don't let it overflow a column and roll back the whole transaction.
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def _clean_ticker(v: object) -> str | None:
    """Coerce LLM output to a real ticker or None.

    The extractor sometimes returns the exchange name ("New York Stock
    Exchange") or a phrase in this field. Tickers are short uppercase tokens;
    anything else gets dropped so we don't trip the column length limit or
    poison the UI.
    """
    if not isinstance(v, str):
        return None
    s = v.strip().upper()
    if not s or not _TICKER_RE.match(s):
        return None
    return s


def _doc_url(cik: str, accession_no_dashes: str, filename: str) -> str:
    return (
        f"{EDGAR_BASE}/Archives/edgar/data/{cik.lstrip('0')}/"
        f"{accession_no_dashes}/{filename}"
    )


async def fetch_filing_bundle(
    edgar: EdgarClient,
    cik: str,
    accession_no_dashes: str,
    *,
    scan_run_id: int | None = None,
    accession_for_logs: str | None = None,
) -> str:
    """Pull the primary form plus the information statement (and the
    separation/distribution agreement when present) and stitch them into a
    single text blob with section markers.

    The 10-12B cover form by itself is just a few pages of boilerplate; nearly
    all the substance the LLM needs — pro-formas, debt sizing, business
    description, owner alignment — lives in the ex99-1 information statement.
    """
    docs = await edgar.list_filing_documents(cik, accession_no_dashes)
    caps = {
        "primary": _PRIMARY_DOC_MAX_CHARS,
        "information_statement": _INFO_STATEMENT_MAX_CHARS,
        "separation_agreement": _SEPARATION_DOC_MAX_CHARS,
    }
    # Pick at most one of each substantive kind. Other exhibits are skipped —
    # they're mostly material contracts whose details would crowd out the
    # information statement without changing the thesis.
    picked: list[dict] = []
    seen_kinds: set[str] = set()
    for d in docs:
        if d["kind"] in caps and d["kind"] not in seen_kinds:
            picked.append(d)
            seen_kinds.add(d["kind"])

    sections: list[str] = []
    total = 0
    for d in picked:
        if total >= _TOTAL_FILING_MAX_CHARS:
            break
        url = _doc_url(cik, accession_no_dashes, d["name"])
        try:
            html = await edgar.fetch_document(url)
        except Exception as exc:
            bus().emit(
                "warn",
                "edgar.exhibit.fail",
                f"Exhibit fetch failed ({d['name']}): {exc}",
                scan_run_id=scan_run_id,
                accession=accession_for_logs,
                filename=d["name"],
            )
            continue
        budget = min(caps[d["kind"]], _TOTAL_FILING_MAX_CHARS - total)
        text = html_to_text(html, max_chars=budget)
        marker = (
            f"\n\n===== DOCUMENT: {d['name']} ({d['kind']}, "
            f"{len(text):,} chars) =====\n\n"
        )
        sections.append(marker + text)
        total += len(text) + len(marker)
        bus().emit(
            "info",
            "edgar.exhibit",
            f"Pulled {d['kind']} {d['name']} ({len(text):,} chars)",
            scan_run_id=scan_run_id,
            accession=accession_for_logs,
            filename=d["name"],
            kind=d["kind"],
            chars=len(text),
        )
    return "".join(sections)


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
    event.parent_name = _trunc(
        extracted.get("parent_name") or filing.company_name, 256
    )
    event.parent_ticker = _clean_ticker(extracted.get("parent_ticker"))
    event.spinco_name = _trunc(extracted.get("spinco_name"), 256)
    event.spinco_ticker = _clean_ticker(extracted.get("expected_ticker_listing"))
    event.distribution_ratio = _trunc(extracted.get("distribution_ratio"), 64)
    event.record_date = extracted.get("_record_date_dt")
    event.distribution_date = extracted.get("_distribution_date_dt")
    event.expected_ticker_listing = event.spinco_ticker

    event.headline = _trunc(scored.get("headline"), 512)
    event.thesis = scored.get("thesis")  # Text column, no length limit
    event.rationale_stated = extracted.get("stated_rationale")  # Text column

    event.score_insider_alignment = axis_score("insider_alignment")
    event.score_forced_selling = axis_score("forced_selling")
    event.score_hidden_value = axis_score("hidden_value")
    event.score_leverage_profile = axis_score("leverage_profile")
    event.score_information_asymmetry = axis_score("information_asymmetry")
    event.composite_score = scored.get("composite_score")

    event.score_rationale = {
        "axes": axes,
        "extracted": {k: v for k, v in extracted.items() if not k.startswith("_")},
        "extraction_evidence": extracted.get("evidence") or {},
        "raw_values": extracted.get("raw_values") or {},
        "inferred_fields": extracted.get("inferred_fields") or [],
        "missing_fields": extracted.get("missing_fields") or [],
        "composite_weights": AXIS_WEIGHTS,
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
                    f"[{i}/{len(refs)}] Fetching {ref.company_name} {ref.form_type} bundle",
                    scan_run_id=scan_run_id,
                    accession=ref.accession_number,
                    url=ref.primary_doc_url,
                )
                accession_no_dashes = ref.accession_number.replace("-", "")
                try:
                    text = await fetch_filing_bundle(
                        edgar,
                        ref.cik,
                        accession_no_dashes,
                        scan_run_id=scan_run_id,
                        accession_for_logs=ref.accession_number,
                    )
                except Exception as exc:
                    bus().emit(
                        "error",
                        "edgar.fetch.fail",
                        f"Fetch failed: {exc}",
                        scan_run_id=scan_run_id,
                        accession=ref.accession_number,
                    )
                    continue
                if not text.strip():
                    bus().emit(
                        "warn",
                        "edgar.empty",
                        f"No usable documents found for {ref.company_name}",
                        scan_run_id=scan_run_id,
                        accession=ref.accession_number,
                    )
                    continue

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
