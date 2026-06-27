"""Server-rendered UI (Jinja2 + HTMX) — the whole frontend, in-process.

This replaces the separate Next.js app: same FastAPI process, one SQLite file,
one systemd unit, no Node/build. It renders HTML pages and small HTMX fragments,
reusing the analysis logic and the JSON API's helper functions directly (no
self-HTTP).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from app.api.chat import chat as chat_api, list_chat as list_chat_api
from app.api.performance import (
    _compute_and_store,
    _is_stale,
    track_record as track_record_api,
    refresh_all as refresh_all_api,
)
from app.api.schemas import ChatRequest
from app.api.scan import _run_scan_task
from app.config import get_settings
from app.db.models import Event, EventType, OutcomeSnapshot, ScanRun
from app.db.session import get_db
from app.fundamentals.massive import Massive
from app.web import charts

router = APIRouter(tags=["web"])

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

AXIS_LABELS: dict[str, dict[str, str]] = {
    "insider_alignment": {
        "title": "Insider alignment",
        "blurb": "Does post-spin management have meaningful skin in the game?",
    },
    "forced_selling": {
        "title": "Forced selling",
        "blurb": "Will mechanical, price-insensitive sellers hit the tape?",
    },
    "hidden_value": {
        "title": "Hidden value",
        "blurb": "Does the rationale point to unlocked value, not defensive moves?",
    },
    "leverage_profile": {
        "title": "Leverage profile",
        "blurb": "Is the capital structure asymmetric in the investor's favor?",
    },
    "information_asymmetry": {
        "title": "Information asymmetry",
        "blurb": "Under-covered enough for an informed investor to have edge?",
    },
}

VERDICT_LABELS = {
    "validated": ("Thesis validated", "ok"),
    "partially_validated": ("Partially validated", "warn"),
    "invalidated": ("Thesis invalidated", "bad"),
    "too_early": ("Too early to judge", "neutral"),
}

AXIS_STATUS = {
    "confirmed": ("✓", "ok"),
    "contradicted": ("✗", "bad"),
    "not_yet_testable": ("·", "neutral"),
}


# --- Jinja filters ----------------------------------------------------------


def _fmt_date(v) -> str:
    if not v:
        return "—"
    if isinstance(v, datetime):
        return v.date().isoformat()
    return str(v)[:10]


def _fmt_pct(v, digits: int = 1) -> str:
    if not isinstance(v, (int, float)):
        return "—"
    return f"{'+' if v >= 0 else ''}{v * 100:.{digits}f}%"


def _fmt_pp(v) -> str:
    if not isinstance(v, (int, float)):
        return "—"
    return f"{'+' if v >= 0 else ''}{v * 100:.1f}pp"


def _fmt_num(v) -> str:
    if not isinstance(v, (int, float)):
        return "—"
    a = abs(v)
    if a >= 1e9:
        return f"${v / 1e9:.2f}B"
    if a >= 1e6:
        return f"${v / 1e6:.1f}M"
    return f"{v:,.0f}"


def _fmt_ratio(v) -> str:
    return f"{v:.2f}×" if isinstance(v, (int, float)) else "—"


def _sign_class(v) -> str:
    if not isinstance(v, (int, float)):
        return "neutral"
    return "ok" if v >= 0 else "bad"


def _score_tone(v) -> str:
    if not isinstance(v, (int, float)):
        return "neutral"
    return "ok" if v >= 7 else "warn" if v >= 5 else "bad"


templates.env.filters.update(
    fmt_date=_fmt_date,
    fmt_pct=_fmt_pct,
    fmt_pp=_fmt_pp,
    fmt_num=_fmt_num,
    fmt_ratio=_fmt_ratio,
    sign_class=_sign_class,
    score_tone=_score_tone,
)


# --- helpers ----------------------------------------------------------------


def _event_or_404(event_id: int, db: Session) -> Event:
    e = (
        db.query(Event)
        .options(joinedload(Event.filing))
        .filter(Event.id == event_id)
        .one_or_none()
    )
    if not e:
        raise HTTPException(404, "event not found")
    return e


def _axes(event: Event) -> list[dict]:
    axes = (event.score_rationale or {}).get("axes") or {}
    out = []
    for name in AXIS_LABELS:
        v = axes.get(name)
        if not isinstance(v, dict):
            continue
        positive = v.get("positive_evidence") or v.get("citations") or []
        out.append(
            {
                "name": name,
                "meta": AXIS_LABELS[name],
                "score": v.get("score"),
                "rationale": v.get("rationale"),
                "confidence": v.get("confidence"),
                "positive": positive,
                "negative": v.get("negative_evidence") or [],
            }
        )
    return out


def _perf_snapshot(db: Session, event: Event, refresh: bool = False) -> OutcomeSnapshot:
    snap = (
        db.query(OutcomeSnapshot)
        .filter(OutcomeSnapshot.event_id == event.id)
        .one_or_none()
    )
    if refresh or snap is None or _is_stale(snap):
        snap = _compute_and_store(db, event, run_llm=True)
    return snap


def _perf_chart(report: dict) -> str:
    legs = report.get("legs", {})
    bm = report.get("benchmarks", {})
    mkt = bm.get("market", {}).get("ticker", "SPY")
    sec = bm.get("sector", {}).get("ticker", mkt)
    series = []
    parent = legs.get("parent")
    spinco = legs.get("spinco")
    if parent and parent.get("series"):
        series.append({"name": f"{parent['ticker']} (parent)", "color": "#a0522d",
                       "points": parent["series"]})
    if spinco and spinco.get("series"):
        series.append({"name": f"{spinco['ticker']} (spinco)", "color": "#0e0f12",
                       "points": spinco["series"]})
    bseries = report.get("benchmark_series", {})
    if bseries.get(mkt):
        series.append({"name": mkt, "color": "#9a958a", "dash": "4 3", "points": bseries[mkt]})
    if sec != mkt and bseries.get(sec):
        series.append({"name": sec, "color": "#b6a98c", "dash": "1 3", "points": bseries[sec]})
    markers = []
    anchors = report.get("anchors", {})
    if anchors.get("filed"):
        markers.append({"date": anchors["filed"], "label": "Filed"})
    if anchors.get("distribution"):
        markers.append({"date": anchors["distribution"], "label": "Distribution"})
    return charts.growth_of_100(series, markers)


def _perf_context(db: Session, event: Event, snap: OutcomeSnapshot) -> dict:
    report = snap.report or {}
    corro = snap.corroboration
    verdict = None
    if corro:
        label, tone = VERDICT_LABELS.get(corro.get("verdict"), VERDICT_LABELS["too_early"])
        axis_assessment = []
        for k, a in (corro.get("axis_assessment") or {}).items():
            mark, tone2 = AXIS_STATUS.get(a.get("status"), AXIS_STATUS["not_yet_testable"])
            axis_assessment.append(
                {"name": k.replace("_", " ").title(), "mark": mark, "tone": tone2,
                 "note": a.get("note")}
            )
        verdict = {
            "label": label, "tone": tone,
            "confidence": round((corro.get("confidence") or 0) * 100),
            "summary": corro.get("summary"),
            "drivers": corro.get("drivers") or [],
            "axis_assessment": axis_assessment,
            "what_to_watch": corro.get("what_to_watch") or [],
        }
    return {
        "event": event,
        "report": report,
        "has_data": bool(report.get("has_data")),
        "chart": _perf_chart(report) if report.get("has_data") else "",
        "verdict": verdict,
        "computed_at": snap.computed_at,
    }


# --- pages ------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    type: str | None = Query(None),
    min: float | None = Query(None),
):
    q = db.query(Event).options(joinedload(Event.filing))
    if type:
        try:
            q = q.filter(Event.event_type == EventType(type))
        except ValueError:
            pass
    if min is not None:
        q = q.filter(Event.composite_score >= min)
    events = q.order_by(desc(Event.composite_score), desc(Event.created_at)).limit(200).all()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"request": request, "events": events, "active_type": type, "active_min": min},
    )


@router.get("/events/{event_id}", response_class=HTMLResponse)
def event_detail(event_id: int, request: Request, db: Session = Depends(get_db)):
    event = _event_or_404(event_id, db)
    market = Massive()
    parent_snap = market.snapshot(event.parent_ticker) if event.parent_ticker else None
    spinco_snap = market.snapshot(event.spinco_ticker) if event.spinco_ticker else None
    snap = _perf_snapshot(db, event)
    messages = list_chat_api(event_id, db)
    return templates.TemplateResponse(
        request,
        "event_detail.html",
        {
            "request": request,
            "event": event,
            "axes": _axes(event),
            "parent_snapshot": parent_snap,
            "spinco_snapshot": spinco_snap,
            "perf": _perf_context(db, event, snap),
            "messages": messages,
        },
    )


@router.get("/scan", response_class=HTMLResponse)
def scan_page(request: Request, db: Session = Depends(get_db)):
    runs = db.query(ScanRun).order_by(desc(ScanRun.started_at)).limit(10).all()
    return templates.TemplateResponse(
        request,
        "scan.html",
        {"request": request, "runs": runs, "default_days": get_settings().scan_lookback_days},
    )


@router.get("/track-record", response_class=HTMLResponse)
def track_record_page(request: Request, db: Session = Depends(get_db)):
    data = track_record_api(db)
    scatter = charts.score_alpha_scatter(
        [
            {"x": it["composite_score"], "y": it["headline"]["market_alpha"],
             "label": it.get("spinco_ticker") or it.get("parent_ticker") or ""}
            for it in data["items"]
            if it.get("headline") and isinstance(it["headline"].get("market_alpha"), (int, float))
            and isinstance(it.get("composite_score"), (int, float))
        ]
    )
    return templates.TemplateResponse(
        request,
        "track_record.html",
        {"request": request, "data": data, "scatter": scatter,
         "verdict_labels": VERDICT_LABELS},
    )


# --- HTMX fragments ---------------------------------------------------------


@router.post("/events/{event_id}/chat", response_class=HTMLResponse)
def chat_fragment(
    event_id: int,
    request: Request,
    db: Session = Depends(get_db),
    question: str = Form(...),
):
    if question.strip():
        chat_api(event_id, ChatRequest(question=question), db)
    messages = list_chat_api(event_id, db)
    return templates.TemplateResponse(
        request,
        "_chat.html", {"request": request, "messages": messages, "event_id": event_id}
    )


@router.post("/events/{event_id}/performance/refresh", response_class=HTMLResponse)
def perf_refresh_fragment(event_id: int, request: Request, db: Session = Depends(get_db)):
    event = _event_or_404(event_id, db)
    snap = _perf_snapshot(db, event, refresh=True)
    return templates.TemplateResponse(
        request,
        "_performance.html", {"request": request, "perf": _perf_context(db, event, snap)}
    )


@router.post("/scan", response_class=HTMLResponse)
async def scan_trigger_fragment(
    request: Request,
    db: Session = Depends(get_db),
    lookback_days: int = Form(...),
):
    import asyncio

    run = ScanRun()
    db.add(run)
    db.commit()
    db.refresh(run)
    asyncio.create_task(_run_scan_task(run.id, lookback_days))
    return templates.TemplateResponse(
        request,
        "_scan_status.html", {"request": request, "run_id": run.id, "running": True}
    )


@router.get("/scan/status/{run_id}", response_class=HTMLResponse)
def scan_status_fragment(run_id: int, request: Request, db: Session = Depends(get_db)):
    run = db.query(ScanRun).filter(ScanRun.id == run_id).one_or_none()
    if not run:
        raise HTTPException(404, "scan run not found")
    return templates.TemplateResponse(
        request,
        "_scan_status.html",
        {"request": request, "run_id": run.id, "running": run.finished_at is None, "run": run},
    )


@router.post("/track-record/recompute", response_class=HTMLResponse)
def track_record_recompute(request: Request, db: Session = Depends(get_db)):
    refresh_all_api(db, run_llm=True, limit=200)
    return track_record_page(request, db)
