"""Historical daily price series via the Massive (Polygon) aggregates API.

The fundamentals snapshot in `massive.py` answers "what is this worth today?".
This module answers "what has the price *done*?" — the raw material for
back-testing a spin-off thesis against what the market actually did after the
event.

Everything here is read-only and defensive: a missing API key, an un-listed
ticker (a spin-co that hasn't started trading yet), or a transient API error
all collapse to an empty series so callers can degrade gracefully.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone

from massive import RESTClient

from app.config import get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Bar:
    """One daily OHLC bar, date normalised to an ISO `YYYY-MM-DD` string."""

    date: str
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None


# Process-wide cache. Price history for a (ticker, from, to) window is
# effectively immutable for closed days, so we keep it for the lifetime of the
# process to avoid re-hitting the rate-limited API while a user clicks around.
_CACHE: dict[tuple[str, str, str], list[Bar]] = {}
_CACHE_AT: dict[tuple[str, str, str], float] = {}
_CACHE_TTL_SECONDS = 60 * 60 * 6  # 6h — enough that "to=today" refreshes intraday-ish


def _to_iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date().isoformat()


def _as_date_str(d: date | datetime | str) -> str:
    if isinstance(d, str):
        return d[:10]
    if isinstance(d, datetime):
        return d.date().isoformat()
    return d.isoformat()


class PriceHistory:
    """Thin, cached wrapper over `RESTClient.list_aggs` for daily bars."""

    def __init__(self) -> None:
        self.api_key = get_settings().polygon_api_key
        self._client: RESTClient | None = None

    def _enabled(self) -> bool:
        return bool(self.api_key)

    def _rest(self) -> RESTClient:
        if self._client is None:
            self._client = RESTClient(api_key=self.api_key)
        return self._client

    def daily(
        self,
        ticker: str,
        start: date | datetime | str,
        end: date | datetime | str | None = None,
    ) -> list[Bar]:
        """Daily bars for `ticker` in [start, end] (inclusive), sorted ascending.

        Returns `[]` for a missing key, an empty ticker, an unlisted ticker, or
        any API error. Never raises — the caller decides what an empty series
        means (often: "this leg of the trade isn't live yet").
        """
        if not ticker or not self._enabled():
            return []
        start_s = _as_date_str(start)
        end_s = _as_date_str(end) if end else date.today().isoformat()
        key = (ticker.upper(), start_s, end_s)

        cached = _CACHE.get(key)
        if cached is not None and (time.time() - _CACHE_AT.get(key, 0)) < _CACHE_TTL_SECONDS:
            return cached

        bars: list[Bar] = []
        try:
            for a in self._rest().list_aggs(
                ticker=ticker,
                multiplier=1,
                timespan="day",
                from_=start_s,
                to=end_s,
                adjusted=True,
                sort="asc",
                limit=50000,
            ):
                ts = getattr(a, "timestamp", None)
                close = getattr(a, "close", None)
                if ts is None or close is None:
                    continue
                bars.append(
                    Bar(
                        date=_to_iso(ts),
                        close=float(close),
                        open=_f(getattr(a, "open", None)),
                        high=_f(getattr(a, "high", None)),
                        low=_f(getattr(a, "low", None)),
                        volume=_f(getattr(a, "volume", None)),
                    )
                )
        except Exception as exc:  # noqa: BLE001 — defensive by design
            log.warning("list_aggs(%s, %s..%s) failed: %s", ticker, start_s, end_s, exc)
            return []

        _CACHE[key] = bars
        _CACHE_AT[key] = time.time()
        return bars


def _f(v: object) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


# --- pure helpers over a Bar series ------------------------------------------


def close_on_or_after(bars: list[Bar], target: date | datetime | str) -> Bar | None:
    """First bar on or after `target` — the realistic fill if you acted that day."""
    t = _as_date_str(target)
    for b in bars:
        if b.date >= t:
            return b
    return None


def close_on_or_before(bars: list[Bar], target: date | datetime | str) -> Bar | None:
    t = _as_date_str(target)
    chosen = None
    for b in bars:
        if b.date <= t:
            chosen = b
        else:
            break
    return chosen


def total_return(bars: list[Bar], start: date | datetime | str | None = None) -> float | None:
    """Total return from the first bar on/after `start` to the last bar.

    `None` means we couldn't anchor a start (no data in range).
    """
    if not bars:
        return None
    first = close_on_or_after(bars, start) if start else bars[0]
    if first is None or not first.close:
        return None
    last = bars[-1]
    return (last.close / first.close) - 1.0


def return_between(
    bars: list[Bar],
    start: date | datetime | str,
    end: date | datetime | str | None = None,
) -> float | None:
    if not bars:
        return None
    first = close_on_or_after(bars, start)
    if first is None or not first.close:
        return None
    last = close_on_or_before(bars, end) if end else bars[-1]
    if last is None or not last.close:
        return None
    return (last.close / first.close) - 1.0


def max_drawdown(bars: list[Bar]) -> float | None:
    """Worst peak-to-trough decline over the series (negative number)."""
    if not bars:
        return None
    peak = bars[0].close
    worst = 0.0
    for b in bars:
        if b.close > peak:
            peak = b.close
        if peak:
            worst = min(worst, (b.close / peak) - 1.0)
    return worst
