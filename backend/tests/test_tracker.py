"""Tests for phase detection, the washout signal, and ticker normalization.

`build_report` is exercised with the market API monkeypatched so we test the
branching logic deterministically without network.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.fundamentals import prices as prices_mod
from app.fundamentals.tickers import _normalize
from app.performance.tracker import _washout, build_report


def _bars(closes, start):
    d0 = date.fromisoformat(start)
    return [
        prices_mod.Bar(date=(d0 + timedelta(days=i)).isoformat(), close=c)
        for i, c in enumerate(closes)
    ]


def _event(**kw):
    base = dict(
        id=1,
        parent_ticker="HON",
        parent_name="Honeywell International Inc.",
        spinco_ticker="HONA",
        spinco_name="Honeywell Aerospace Inc.",
        record_date=None,
        distribution_date=None,
        rationale_stated="aerospace separation",
        filing=SimpleNamespace(filed_at=datetime(2026, 6, 8, tzinfo=timezone.utc)),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _patch_prices(monkeypatch, table):
    """table: ticker -> list[Bar]. Anything not in the table returns []."""

    def fake_daily(self, ticker, start, end=None):
        return table.get((ticker or "").upper(), [])

    monkeypatch.setattr(prices_mod.PriceHistory, "daily", fake_daily)


def test_phase_pre_distribution_when_spinco_not_trading(monkeypatch):
    # Bars must span the filing date (2026-06-08) for the since-filing window
    # to anchor.
    _patch_prices(
        monkeypatch,
        {
            "HON": _bars([100, 105, 110], "2026-06-08"),
            "SPY": _bars([100, 100, 101], "2026-06-08"),
            "XAR": _bars([100, 101, 102], "2026-06-08"),
            # HONA absent → not trading
        },
    )
    e = _event(distribution_date=datetime(2026, 6, 29, tzinfo=timezone.utc))
    r = build_report(e)
    assert r["phase"] == "pre_distribution"
    assert r["legs"]["spinco"]["trading"] is False
    # headline should fall back to the parent's since-filing window
    assert r["headline"]["subject"] == "HON"
    assert r["benchmarks"]["sector"]["ticker"] == "XAR"


def test_phase_seasoning_when_spinco_recently_trading(monkeypatch):
    today = date.today()
    start = (today - timedelta(days=20)).isoformat()
    _patch_prices(
        monkeypatch,
        {
            "HON": _bars([100, 101], start),
            "HONA": _bars([50, 52, 55], start),
            "SPY": _bars([100, 100], start),
            "XAR": _bars([100, 100], start),
        },
    )
    e = _event(distribution_date=datetime.combine(today - timedelta(days=20), datetime.min.time(), tzinfo=timezone.utc))
    r = build_report(e)
    assert r["phase"] == "seasoning"
    assert r["legs"]["spinco"]["trading"] is True


def test_phase_seasoned_when_old(monkeypatch):
    today = date.today()
    start = (today - timedelta(days=200)).isoformat()
    _patch_prices(
        monkeypatch,
        {
            "HON": _bars([100, 101], start),
            "HONA": _bars([50] + [51] * 150, start),
            "SPY": _bars([100, 101], start),
            "XAR": _bars([100, 101], start),
        },
    )
    e = _event(distribution_date=datetime.combine(today - timedelta(days=200), datetime.min.time(), tzinfo=timezone.utc))
    r = build_report(e)
    assert r["phase"] == "seasoned"


def test_no_data_when_no_ticker(monkeypatch):
    _patch_prices(monkeypatch, {})
    e = _event(parent_ticker=None, spinco_ticker=None)
    r = build_report(e)
    assert r["phase"] == "no_data"
    assert r["has_data"] is False


def test_washout_measures_trough_and_recovery():
    bars = _bars([100, 80, 70, 90], "2026-03-01")  # trough 70 = -30%, recover to 90
    w = _washout(bars)
    assert w["trough_return"] < 0
    assert round(w["trough_return"], 2) == -0.30
    assert w["recovery_from_trough"] == round(90 / 70 - 1, 10) or w["recovery_from_trough"] > 0
    assert w["still_below_first"] is True


def test_normalize_strips_suffixes_and_cik():
    assert _normalize("The Middleby Corporation") == "middleby"
    assert _normalize("S&P Global Inc.") == "s p global"
    assert _normalize("TX Rail Products, Inc.  (CIK 0001133798)") == "tx rail products"
    assert _normalize("Resideo Technologies, Inc.") == "resideo technologies"
