"""Turn an Event + price history into a phase-aware outcome report.

The report is the factual half of the loop — what the market actually did.
`corroborate.py` then asks the LLM the interpretive half — whether the thesis
explains it. Keeping them separate means the numbers are always trustworthy
even if the LLM is unavailable.

Design notes for the fund-manager lens:

* A spin-off is not a point event, it's a *sequence*: filing → record date →
  distribution → seasoning. The value shows up in different legs at different
  times. Pre-distribution, you watch the **parent** re-rate in anticipation.
  Post-distribution, you watch the **spin-co** survive the forced-selling
  washout. The `phase` field drives which leg is the headline.
* Absolute return is a vanity metric. Every window carries `market_alpha`
  (vs SPY) and `sector_alpha` (vs the industry ETF) so you can see whether the
  *edge* was real or just beta.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.db.models import Event
from app.fundamentals.prices import (
    Bar,
    PriceHistory,
    close_on_or_after,
    return_between,
)
from app.performance.benchmarks import MARKET_BENCHMARK, sector_benchmark

# Greenblatt's "forced selling" window: index funds and parent shareholders who
# don't want the small spin-co dump it in roughly the first quarter, often
# creating the entry point. We measure the washout over this horizon.
WASHOUT_WINDOW_DAYS = 90
SEASONING_DAYS = 90  # below this many days post-distribution, the spin is "seasoning"

# How far before the filing to pull, so the chart has a little run-in context.
PRE_FILING_BUFFER_DAYS = 10


def _d(dt: datetime | date | None) -> date | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.astimezone(timezone.utc).date() if dt.tzinfo else dt.date()
    return dt


def _series_payload(bars: list[Bar]) -> list[dict]:
    return [{"date": b.date, "close": b.close} for b in bars if b.close]


def _window(
    asset: list[Bar],
    market: list[Bar],
    sector: list[Bar],
    start: date,
    *,
    label: str,
    end: date | None = None,
) -> dict | None:
    r = return_between(asset, start, end)
    if r is None:
        return None
    mkt = return_between(market, start, end)
    sec = return_between(sector, start, end)
    anchor = close_on_or_after(asset, start)
    last = asset[-1]
    return {
        "label": label,
        "from": anchor.date if anchor else start.isoformat(),
        "to": (end.isoformat() if end else last.date),
        "return": r,
        "market_return": mkt,
        "sector_return": sec,
        "market_alpha": (r - mkt) if mkt is not None else None,
        "sector_alpha": (r - sec) if sec is not None else None,
    }


def _washout(spinco: list[Bar]) -> dict | None:
    """Quantify the forced-selling dip in the first WASHOUT_WINDOW_DAYS of trading."""
    if not spinco:
        return None
    first = spinco[0]
    if not first.close:
        return None
    start = date.fromisoformat(first.date)
    horizon = [b for b in spinco if (date.fromisoformat(b.date) - start).days <= WASHOUT_WINDOW_DAYS]
    if len(horizon) < 2:
        return None
    trough = min(horizon, key=lambda b: b.close)
    trough_return = (trough.close / first.close) - 1.0
    last = spinco[-1]
    recovery = (last.close / trough.close) - 1.0 if trough.close else None
    return {
        "applicable": True,
        "first_close": first.close,
        "first_date": first.date,
        "trough_close": trough.close,
        "trough_date": trough.date,
        "trough_return": trough_return,
        "latest_close": last.close,
        "recovery_from_trough": recovery,
        "window_days": WASHOUT_WINDOW_DAYS,
        "still_below_first": last.close < first.close,
    }


def build_report(event: Event) -> dict:
    """Compute the full outcome report for a spin-off event."""
    ph = PriceHistory()
    today = date.today()

    filed = _d(event.filing.filed_at) if event.filing else None
    record = _d(event.record_date)
    distribution = _d(event.distribution_date)

    parent_ticker = (event.parent_ticker or "").upper() or None
    spinco_ticker = (event.spinco_ticker or "").upper() or None

    sector_etf, sector_label = sector_benchmark(
        event.parent_name, event.spinco_name, event.rationale_stated
    )

    # Pull window: a touch before the filing through today.
    pull_start = filed or (today.replace(year=today.year - 1))
    if filed:
        pull_start = date.fromordinal(filed.toordinal() - PRE_FILING_BUFFER_DAYS)

    parent_bars = ph.daily(parent_ticker, pull_start, today) if parent_ticker else []
    # Only chase spin-co history once it could plausibly trade — i.e. there's no
    # distribution date yet, or it has already passed. Starting the pull at a
    # future distribution date makes from > to and the API rejects it.
    spinco_can_trade = spinco_ticker and (distribution is None or distribution <= today)
    spinco_start = distribution or pull_start
    spinco_bars = ph.daily(spinco_ticker, spinco_start, today) if spinco_can_trade else []
    market_bars = ph.daily(MARKET_BENCHMARK, pull_start, today)
    sector_bars = ph.daily(sector_etf, pull_start, today) if sector_etf != MARKET_BENCHMARK else market_bars

    notes: list[str] = []

    # --- phase detection ----------------------------------------------------
    spinco_trading = len(spinco_bars) >= 2
    days_since_dist = (today - distribution).days if distribution else None

    if spinco_trading:
        if days_since_dist is not None and days_since_dist < SEASONING_DAYS:
            phase, phase_label = "seasoning", "Seasoning (forced-selling window)"
        else:
            phase, phase_label = "seasoned", "Seasoned"
    elif distribution and distribution > today:
        phase, phase_label = "pre_distribution", "Announced — awaiting distribution"
        notes.append(
            f"Spin-off distributes {distribution.isoformat()}; "
            f"{spinco_ticker or 'the spin-co'} is not trading yet. "
            "Tracking the parent's anticipation re-rating."
        )
    elif not parent_ticker:
        phase, phase_label = "no_data", "No ticker resolved"
        notes.append("No parent ticker on this event, so no price history is available.")
    else:
        phase, phase_label = "pre_distribution", "Announced — awaiting distribution"

    if spinco_ticker and not spinco_trading and (distribution and distribution <= today):
        notes.append(
            f"{spinco_ticker} has no price history yet despite a past distribution date "
            "— it may trade under a when-issued or different symbol."
        )

    # --- per-leg windows ----------------------------------------------------
    def leg(ticker: str | None, name: str | None, bars: list[Bar]) -> dict | None:
        if not ticker:
            return None
        windows: dict[str, dict] = {}
        if bars:
            if filed:
                w = _window(bars, market_bars, sector_bars, filed, label="Since filing")
                if w:
                    windows["since_filing"] = w
            if distribution and distribution <= today:
                w = _window(bars, market_bars, sector_bars, distribution, label="Since distribution")
                if w:
                    windows["since_distribution"] = w
        return {
            "ticker": ticker,
            "name": name,
            "trading": len(bars) >= 2,
            "first_close": bars[0].close if bars else None,
            "first_date": bars[0].date if bars else None,
            "last_close": bars[-1].close if bars else None,
            "last_date": bars[-1].date if bars else None,
            "series": _series_payload(bars),
            "windows": windows,
        }

    parent_leg = leg(parent_ticker, event.parent_name, parent_bars)
    spinco_leg = leg(spinco_ticker, event.spinco_name, spinco_bars)

    # --- headline: the window a fund manager would actually quote -----------
    headline = _headline(phase, parent_leg, spinco_leg)

    washout = _washout(spinco_bars) if spinco_trading else None

    return {
        "event_id": event.id,
        "as_of": today.isoformat(),
        "phase": phase,
        "phase_label": phase_label,
        "days_since_distribution": days_since_dist,
        "anchors": {
            "filed": filed.isoformat() if filed else None,
            "record": record.isoformat() if record else None,
            "distribution": distribution.isoformat() if distribution else None,
        },
        "benchmarks": {
            "market": {"ticker": MARKET_BENCHMARK, "label": "S&P 500 (SPY)"},
            "sector": {"ticker": sector_etf, "label": sector_label},
        },
        "benchmark_series": {
            MARKET_BENCHMARK: _series_payload(market_bars),
            sector_etf: _series_payload(sector_bars),
        },
        "legs": {"parent": parent_leg, "spinco": spinco_leg},
        "washout": washout,
        "headline": headline,
        "notes": notes,
        "has_data": bool(parent_bars or spinco_bars),
    }


def _headline(phase: str, parent_leg: dict | None, spinco_leg: dict | None) -> dict | None:
    """Pick the single return statistic that best summarises the outcome so far."""
    def pick(leg: dict | None, key: str) -> dict | None:
        if leg and leg.get("windows", {}).get(key):
            w = leg["windows"][key]
            return {
                "subject": leg["ticker"],
                "subject_role": None,  # filled below
                "window": w["label"],
                "return": w["return"],
                "market_alpha": w["market_alpha"],
                "sector_alpha": w["sector_alpha"],
            }
        return None

    if phase in ("seasoning", "seasoned"):
        h = pick(spinco_leg, "since_distribution") or pick(parent_leg, "since_distribution")
        if h:
            h["subject_role"] = "spinco" if (spinco_leg and h["subject"] == spinco_leg["ticker"]) else "parent"
            return h
    # pre-distribution (or no spin data): the parent's run-up since the filing.
    h = pick(parent_leg, "since_filing") or pick(spinco_leg, "since_filing")
    if h:
        h["subject_role"] = "parent" if (parent_leg and h["subject"] == parent_leg["ticker"]) else "spinco"
        return h
    return None
