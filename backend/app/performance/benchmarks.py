"""Pick the right yardstick for a spin-off.

Absolute return tells you almost nothing — a spin-co that rose 20% in a market
that rose 25% was a *loser*. To judge a thesis you need two benchmarks:

  * the **market** (SPY) — strips out beta, answers "did this beat just owning
    the index?";
  * the **sector** (an industry ETF) — strips out sector tailwinds, answers
    "did the special-situations *edge* show up, or did we just ride defense
    spending / rates / whatever?".

The sector mapping is a deliberately small keyword heuristic over the company
name + SIC description. It biases toward the handful of liquid sector ETFs a
generalist event-driven fund would actually benchmark against, and falls back
to SPY when nothing matches (better an honest market benchmark than a wrong
sector one).
"""

from __future__ import annotations

MARKET_BENCHMARK = "SPY"

# (keywords, etf, human label). First match wins, so order specific → general.
_SECTOR_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("aerospace", "aircraft", "defense", "avionic"), "XAR", "Aerospace & Defense"),
    (("airline", "airport"), "JETS", "Airlines"),
    (("semiconductor", "chip"), "SMH", "Semiconductors"),
    (("software", "saas", "internet", "cloud"), "IGV", "Software"),
    (("bank", "insurance", "financial", "asset management", "brokerage"), "XLF", "Financials"),
    (("biotech", "biopharm", "pharma", "therapeutic", "drug", "biolog"), "XBI", "Biotech / Pharma"),
    (("hospital", "health", "medical", "device", "care"), "XLV", "Health Care"),
    (("oil", "gas", "energy", "petroleum", "drilling", "refin"), "XLE", "Energy"),
    (("mining", "metal", "steel", "chemical", "material", "mineral"), "XLB", "Materials"),
    (("retail", "consumer", "apparel", "restaurant", "store"), "XLY", "Consumer Discretionary"),
    (("food", "beverage", "household", "staple", "tobacco"), "XLP", "Consumer Staples"),
    (("reit", "real estate", "property", "realty"), "XLRE", "Real Estate"),
    (("utility", "electric", "power", "water"), "XLU", "Utilities"),
    (("industrial", "machinery", "manufactur", "equipment", "distribut", "logistic"),
     "XLI", "Industrials"),
    (("media", "entertainment", "telecom", "communication", "broadcast"),
     "XLC", "Communication Services"),
]


def sector_benchmark(*texts: str | None) -> tuple[str, str]:
    """Return (etf_ticker, label) for the best-matching sector, else SPY.

    Pass any descriptive strings (company name, SIC description, industry). The
    match is case-insensitive substring over the concatenation.
    """
    hay = " ".join(t for t in texts if t).lower()
    for keywords, etf, label in _SECTOR_RULES:
        if any(k in hay for k in keywords):
            return etf, label
    return MARKET_BENCHMARK, "Broad market"
