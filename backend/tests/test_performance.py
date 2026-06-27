"""Unit tests for the outcome-tracking engine.

These cover the *pure* logic — price math, benchmark selection, phase detection,
name→ticker normalization, and the LLM prompt formatting — without hitting the
market API or OpenAI. The network-touching wrappers degrade to empty results by
design, so the logic is what's worth pinning down.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.fundamentals.prices import (
    Bar,
    close_on_or_after,
    close_on_or_before,
    max_drawdown,
    return_between,
    total_return,
)
from app.performance.benchmarks import sector_benchmark
from app.performance.corroborate import _beat, _format_leg, _pct, _pp


def _series(closes: list[float], start="2026-01-01") -> list[Bar]:
    d0 = date.fromisoformat(start)
    return [Bar(date=(d0 + timedelta(days=i)).isoformat(), close=c) for i, c in enumerate(closes)]


# --- price math --------------------------------------------------------------


def test_total_return_simple():
    bars = _series([100, 110])
    assert total_return(bars) == pytest.approx(0.10)


def test_total_return_empty_is_none():
    assert total_return([]) is None


def test_return_between_anchors_on_or_after_start():
    bars = _series([100, 105, 120], start="2026-01-01")
    # Start mid-series → anchor on the 2nd bar (105) → 120/105 - 1.
    r = return_between(bars, "2026-01-02")
    assert r == pytest.approx(120 / 105 - 1)


def test_return_between_respects_end():
    bars = _series([100, 105, 120, 90])
    r = return_between(bars, "2026-01-01", "2026-01-03")  # through the 120 bar
    assert r == pytest.approx(0.20)


def test_close_on_or_after_and_before():
    bars = _series([100, 105, 120])
    assert close_on_or_after(bars, "2026-01-02").close == 105
    assert close_on_or_before(bars, "2026-01-02").close == 105
    assert close_on_or_after(bars, "2026-12-31") is None
    assert close_on_or_before(bars, "2025-12-31") is None


def test_max_drawdown():
    bars = _series([100, 120, 60, 90])  # peak 120 → trough 60 = -50%
    assert max_drawdown(bars) == pytest.approx(-0.5)


def test_alpha_is_relative_return():
    """Regression for the Honeywell bug: positive alpha == outperformance."""
    asset = _series([100, 110])  # +10%
    market = _series([100, 99])  # -1%
    asset_r = total_return(asset)
    market_r = total_return(market)
    alpha = asset_r - market_r
    assert alpha > 0  # asset beat the market
    assert _beat(alpha) == "OUTPERFORMED"


# --- benchmark selection -----------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Honeywell Aerospace Inc.", "XAR"),
        ("Acme Biopharma therapeutics", "XBI"),
        ("Global Semiconductor Holdings", "SMH"),
        ("First National Bank Corp", "XLF"),
        ("Sunrise Oil & Gas Partners", "XLE"),
        ("Generic Whatchamacallit Co", "SPY"),  # no keyword → market fallback
    ],
)
def test_sector_benchmark(text, expected):
    etf, _label = sector_benchmark(text)
    assert etf == expected


def test_sector_benchmark_first_match_wins():
    # "aerospace" precedes "industrial" in the rules → aerospace.
    etf, _ = sector_benchmark("Aerospace industrial machinery group")
    assert etf == "XAR"


# --- corroboration formatting (no LLM) --------------------------------------


def test_pct_and_pp_formatting():
    assert _pct(0.096) == "+9.6%"
    assert _pp(0.110) == "+11.0pp"
    assert _pct(None) == "n/a"
    assert _beat(-0.02) == "UNDERPERFORMED"
    assert _beat(0) == "matched"


def test_format_leg_spells_out_outperformance():
    leg = {
        "ticker": "HON",
        "name": "Honeywell",
        "trading": True,
        "first_close": 217.0,
        "first_date": "2026-05-29",
        "last_close": 232.0,
        "last_date": "2026-06-26",
        "windows": {
            "since_filing": {
                "label": "Since filing",
                "return": 0.096,
                "market_return": -0.014,
                "sector_return": 0.011,
                "market_alpha": 0.110,
                "sector_alpha": 0.085,
            }
        },
    }
    out = _format_leg("Parent", leg)
    assert "OUTPERFORMED the market by +11.0pp" in out
    assert "returned +9.6%" in out
    # The market's own return must be present so the model can't confuse alpha
    # with the benchmark return (the original Honeywell failure mode).
    assert "market returned -1.4%" in out


def test_format_leg_handles_not_trading():
    leg = {"ticker": "HONA", "trading": False, "windows": {}}
    assert "not trading yet" in _format_leg("SpinCo", leg)
