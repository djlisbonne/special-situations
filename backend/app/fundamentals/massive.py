"""Massive (formerly Polygon.io) market data client.

Thin wrapper around the official `massive` Python SDK
(https://github.com/massive-com/client-python). The SDK returns typed
dataclasses (TickerDetails, TickerSnapshot, StockFinancial) which we mash into
the flat dict the event detail page renders.

If `POLYGON_API_KEY` is empty the calls return None / {} and the UI gracefully
omits these fields.
"""

from __future__ import annotations

import logging
from typing import Any

from massive import RESTClient
from massive.rest.models.financials import (
    BalanceSheet,
    CashFlowStatement,
    Financials,
    IncomeStatement,
    StockFinancial,
)

from app.config import get_settings

log = logging.getLogger(__name__)


def _v(node: Any, *attrs: str) -> float | None:
    """Pull a numeric value off the first matching DataPoint attribute.

    The financial-statement dataclasses expose each GAAP concept as
    `Optional[DataPoint]` where DataPoint has a `.value`. Some concepts have
    multiple synonymous names (e.g., short_term_debt vs current_debt); pass
    them in priority order.
    """
    if node is None:
        return None
    for a in attrs:
        dp = getattr(node, a, None)
        val = getattr(dp, "value", None) if dp is not None else None
        if isinstance(val, (int, float)):
            return float(val)
    return None


class Massive:
    def __init__(self) -> None:
        self.api_key = get_settings().polygon_api_key
        self._client: RESTClient | None = None

    def _enabled(self) -> bool:
        return bool(self.api_key)

    def _rest(self) -> RESTClient:
        if self._client is None:
            self._client = RESTClient(api_key=self.api_key)
        return self._client

    # --- raw endpoints --------------------------------------------------

    def ticker_details(self, ticker: str) -> Any | None:
        if not self._enabled():
            return None
        try:
            return self._rest().get_ticker_details(ticker=ticker)
        except Exception as exc:
            log.warning("ticker_details(%s) failed: %s", ticker, exc)
            return None

    def snapshot_quote(self, ticker: str) -> Any | None:
        if not self._enabled():
            return None
        try:
            return self._rest().get_snapshot_ticker(market_type="stocks", ticker=ticker)
        except Exception as exc:
            log.warning("snapshot_ticker(%s) failed: %s", ticker, exc)
            return None

    def _financials_lister(self):
        """Locate the financials lister across `massive` SDK versions.

        Some builds expose `RESTClient.list_stock_financials` directly; others
        nest the (experimental) endpoint under `.vx`. Resolve whichever exists
        so a version bump on a fresh install doesn't silently drop fundamentals.
        """
        client = self._rest()
        for owner in (client, getattr(client, "vx", None)):
            fn = getattr(owner, "list_stock_financials", None)
            if callable(fn):
                return fn
        return None

    def latest_financials(self, ticker: str, timeframe: str = "ttm") -> StockFinancial | None:
        if not self._enabled():
            return None
        fn = self._financials_lister()
        if fn is None:
            log.warning(
                "massive SDK exposes no list_stock_financials (checked client and .vx); "
                "fundamentals snapshot will be omitted"
            )
            return None
        try:
            for row in fn(ticker=ticker, timeframe=timeframe, limit=1, order="desc"):
                return row
        except Exception as exc:
            log.warning("list_stock_financials(%s, %s) failed: %s", ticker, timeframe, exc)
        return None

    # --- combined snapshot ---------------------------------------------

    def snapshot(self, ticker: str) -> dict:
        """One call site that gathers everything the detail page renders."""
        if not ticker or not self._enabled():
            return {}

        details = self.ticker_details(ticker)
        quote = self.snapshot_quote(ticker)
        fin = self.latest_financials(ticker) or self.latest_financials(ticker, "annual")

        # Statements
        statements: Financials | None = getattr(fin, "financials", None)
        income: IncomeStatement | None = getattr(statements, "income_statement", None)
        balance: BalanceSheet | None = getattr(statements, "balance_sheet", None)
        cashflow: CashFlowStatement | None = getattr(statements, "cash_flow_statement", None)

        market_cap = getattr(details, "market_cap", None)
        exchange = getattr(details, "primary_exchange", None)
        industry = getattr(details, "sic_description", None)
        name = getattr(details, "name", None)

        # Snapshot price: SDK's TickerSnapshot has .last_trade.price and .day.close
        last_trade = getattr(quote, "last_trade", None)
        day = getattr(quote, "day", None)
        price = getattr(last_trade, "price", None) or getattr(day, "close", None)

        # EBITDA ≈ operating income + D&A
        op_income = _v(income, "operating_income_loss")
        dep_amort = _v(cashflow, "depreciation_amortization_and_accretion") or _v(
            income, "depreciation_and_amortization"
        )
        ebitda = (
            op_income + dep_amort
            if op_income is not None and dep_amort is not None
            else None
        )

        long_debt = _v(balance, "long_term_debt") or 0.0
        short_debt = _v(balance, "current_debt", "short_term_debt") or 0.0
        cash = _v(balance, "cash", "cash_and_cash_equivalents") or 0.0
        has_debt_signal = any(
            _v(balance, k) is not None
            for k in (
                "long_term_debt",
                "current_debt",
                "short_term_debt",
                "cash",
                "cash_and_cash_equivalents",
            )
        )
        net_debt = (long_debt + short_debt - cash) if has_debt_signal else None

        ev = (market_cap + net_debt) if (market_cap and net_debt is not None) else None
        ev_ebitda = (ev / ebitda) if (ev and ebitda) else None
        net_debt_ebitda = (
            net_debt / ebitda if (net_debt is not None and ebitda) else None
        )

        net_income = _v(income, "net_income_loss")
        earnings_yield = (net_income / market_cap) if (net_income and market_cap) else None

        cfo = _v(cashflow, "net_cash_flow_from_operating_activities")
        capex = _v(
            cashflow,
            "payments_for_property_plant_and_equipment",
            "purchase_of_property_plant_and_equipment",
        )
        fcf = (cfo + capex) if (cfo is not None and capex is not None) else cfo
        fcf_yield = (fcf / market_cap) if (fcf and market_cap) else None

        equity = _v(balance, "equity", "stockholders_equity")
        tax_rate = 0.21
        nopat = (op_income * (1 - tax_rate)) if op_income is not None else None
        invested_capital = (
            equity + net_debt if (equity is not None and net_debt is not None) else None
        )
        roic = (
            nopat / invested_capital
            if (nopat is not None and invested_capital)
            else None
        )

        return {
            "ticker": ticker,
            "name": name,
            "exchange": exchange,
            "industry": industry,
            "market_cap": market_cap,
            "price": price,
            "ev": ev,
            "ev_to_ebitda": ev_ebitda,
            "earnings_yield": earnings_yield,
            "roic": roic,
            "net_debt_to_ebitda": net_debt_ebitda,
            "fcf_yield": fcf_yield,
            "fiscal_period": getattr(fin, "fiscal_period", None),
            "fiscal_year": getattr(fin, "fiscal_year", None),
            "source": "massive",
        }
