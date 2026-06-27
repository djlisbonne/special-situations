"""LLM half of the loop: did the thesis explain what the market did?

We hand the model three things and nothing else:

  1. the original thesis + per-axis Greenblatt scores (the *prediction*);
  2. a compact, pre-computed price-action summary (the *outcome*);
  3. the rules of engagement (attribute alpha vs. beta, don't invent data).

The price math is done in Python (`tracker.py`) and only the conclusions are
fed in, so the model can't fabricate returns — it can only interpret the ones
we measured. The output is a structured verdict the UI renders next to the
scores, closing the predict → observe → explain loop.
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.db.models import Event
from app.llm.client import structured_chat
from app.llm.schemas import THESIS_CORROBORATION_SCHEMA

log = logging.getLogger(__name__)

SYSTEM = """You are a post-mortem analyst for an event-driven hedge fund that \
trades spin-offs in the tradition of Joel Greenblatt.

You are given (a) the fund's ORIGINAL thesis and per-axis scores for a spin-off, \
and (b) a factual summary of what the stock(s) actually did, already measured \
against the S&P 500 and the relevant sector ETF.

Your job is to judge whether the thesis is playing out, and crucially WHY. \
Rules:
- Distinguish alpha from beta. If the position rose but lagged its sector, say \
  the edge did NOT show up. Market_alpha and sector_alpha are the truth tellers.
- Respect the phase. Pre-distribution, the only testable thing is whether the \
  parent re-rated in anticipation; the spin-co's forced-selling thesis is \
  'not_yet_testable'. Don't grade axes the data can't yet speak to.
- Never invent prices, dates, or news beyond what you are given. If something \
  is unknowable from the data, say so in 'what_to_watch'.
- Be concrete and quantitative: cite the actual return and alpha figures."""


def _pct(x: float | None) -> str:
    return f"{x * 100:+.1f}%" if isinstance(x, (int, float)) else "n/a"


def _pp(x: float | None) -> str:
    """Format alpha as percentage POINTS to keep it distinct from a return."""
    return f"{x * 100:+.1f}pp" if isinstance(x, (int, float)) else "n/a"


def _beat(alpha: float | None) -> str:
    if not isinstance(alpha, (int, float)):
        return "n/a"
    return "OUTPERFORMED" if alpha > 0 else "UNDERPERFORMED" if alpha < 0 else "matched"


def _format_leg(label: str, leg: dict | None) -> str:
    if not leg:
        return f"{label}: not applicable."
    if not leg.get("trading"):
        return f"{label} ({leg['ticker']}): not trading yet."
    lines = [
        f"{label} ({leg['ticker']}, {leg.get('name') or ''}): "
        f"{leg.get('first_close')} on {leg.get('first_date')} → "
        f"{leg.get('last_close')} on {leg.get('last_date')}."
    ]
    for w in leg.get("windows", {}).values():
        # Spell everything out so the model never has to derive the sign of an
        # alpha: give each benchmark's OWN return, then the explicit verdict.
        lines.append(
            f"  • {w['label']}: {leg['ticker']} returned {_pct(w['return'])}. "
            f"Over the same window the market returned {_pct(w['market_return'])} "
            f"and the sector returned {_pct(w['sector_return'])}. "
            f"=> {leg['ticker']} {_beat(w['market_alpha'])} the market by "
            f"{_pp(w['market_alpha'])} and {_beat(w['sector_alpha'])} the sector by "
            f"{_pp(w['sector_alpha'])}. (Positive alpha = the spin-specific edge showed up.)"
        )
    return "\n".join(lines)


def _format_axes(event: Event) -> str:
    axes = (event.score_rationale or {}).get("axes") or {}
    if not axes:
        return "(no per-axis scores recorded)"
    out = []
    for name, v in axes.items():
        if isinstance(v, dict):
            out.append(f"- {name}: {v.get('score')}/10 — {v.get('rationale') or ''}")
    return "\n".join(out)


def build_prompt(event: Event, report: dict) -> str:
    bm = report.get("benchmarks", {})
    wash = report.get("washout")
    parts = [
        f"SPIN-OFF: {event.parent_name} ({event.parent_ticker}) "
        f"→ {event.spinco_name} ({event.spinco_ticker or 'n/a'}).",
        f"Composite score at filing: {event.composite_score}/10.",
        f"Headline thesis: {event.headline}",
        f"Full thesis: {event.thesis}",
        "",
        "ORIGINAL PER-AXIS SCORES (the prediction):",
        _format_axes(event),
        "",
        f"PHASE: {report.get('phase_label')} "
        f"(days since distribution: {report.get('days_since_distribution')}).",
        f"Benchmarks — market: {bm.get('market', {}).get('label')}; "
        f"sector: {bm.get('sector', {}).get('label')}.",
        "Key dates: "
        f"filed {report['anchors'].get('filed')}, "
        f"record {report['anchors'].get('record')}, "
        f"distribution {report['anchors'].get('distribution')}.",
        "",
        "REALIZED PRICE ACTION (the outcome):",
        _format_leg("Parent", report["legs"].get("parent")),
        _format_leg("SpinCo", report["legs"].get("spinco")),
    ]
    if wash and wash.get("applicable"):
        parts += [
            "",
            "FORCED-SELLING WASHOUT (spin-co, first %d days):" % wash["window_days"],
            f"  trough {_pct(wash['trough_return'])} on {wash['trough_date']}, "
            f"recovery from trough {_pct(wash['recovery_from_trough'])}, "
            f"still below first close: {wash['still_below_first']}.",
        ]
    if report.get("notes"):
        parts += ["", "DATA NOTES:", *[f"- {n}" for n in report["notes"]]]
    return "\n".join(parts)


def corroborate(event: Event, report: dict) -> dict | None:
    """Run the LLM post-mortem. Returns the structured verdict, or None on failure.

    Returns None (rather than raising) when there's no price data to judge or
    the API is unavailable, so the performance endpoint still serves the
    factual report.
    """
    if not report.get("has_data"):
        return None
    s = get_settings()
    if not s.openai_api_key:
        return None
    try:
        result = structured_chat(
            model=s.openai_model_primary,
            system=SYSTEM,
            input_data=build_prompt(event, report),
            schema=THESIS_CORROBORATION_SCHEMA,
            max_tokens=1500,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        log.warning("corroborate(event=%s) failed: %s", event.id, exc)
        return None
