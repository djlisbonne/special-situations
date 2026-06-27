"""Resolve a company *name* to its ticker via SEC's official mapping.

Why name-based and not CIK-based: in our data the spin-off is registered by the
*new* entity, so the filing CIK belongs to the spin-co (freshly assigned, no
ticker yet), not the established parent. The parent we know only by name, pulled
from the filing text. SEC publishes `company_tickers.json` (ticker ⇄ title ⇄
CIK) which lets us go name → ticker for the parent.

Matching is deliberately strict. In a tool that feeds trade ideas, a *wrong*
ticker (silently benchmarking the wrong company) is far more dangerous than a
missing one, so we only accept an exact match on a normalized name and refuse
fuzzy/contains guesses.
"""

from __future__ import annotations

import logging
import re
import time

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

_INDEX: dict[str, str] | None = None
_INDEX_AT: float = 0.0
_INDEX_TTL = 60 * 60 * 24  # refresh daily

# Corporate suffixes / filler stripped before comparing names.
_SUFFIXES = re.compile(
    r"\b(incorporated|inc|corporation|corp|company|co|limited|ltd|llc|lp|plc|"
    r"holdings|holding|group|the|sa|nv|ag|class\s+[a-c])\b",
    re.IGNORECASE,
)


def _normalize(name: str) -> str:
    # Drop a trailing "(CIK 000...)" annotation our scraper sometimes appends.
    name = re.sub(r"\(cik[^)]*\)", " ", name, flags=re.IGNORECASE)
    name = name.lower()
    name = _SUFFIXES.sub(" ", name)
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _load_index() -> dict[str, str]:
    global _INDEX, _INDEX_AT
    if _INDEX is not None and (time.time() - _INDEX_AT) < _INDEX_TTL:
        return _INDEX
    ua = get_settings().sec_edgar_user_agent
    index: dict[str, str] = {}
    try:
        r = httpx.get(_SEC_TICKERS_URL, headers={"User-Agent": ua}, timeout=30)
        r.raise_for_status()
        for row in r.json().values():
            title = row.get("title")
            ticker = row.get("ticker")
            if not title or not ticker:
                continue
            key = _normalize(title)
            # First writer wins; SEC lists the primary common share first, so we
            # avoid clobbering "FORD MOTOR CO" with a warrant line later.
            index.setdefault(key, ticker.upper())
    except Exception as exc:  # noqa: BLE001
        log.warning("could not load SEC company_tickers.json: %s", exc)
        return _INDEX or {}
    _INDEX = index
    _INDEX_AT = time.time()
    return index


def resolve_ticker(name: str | None) -> str | None:
    """Exact normalized-name match → ticker, else None. Never guesses."""
    if not name:
        return None
    idx = _load_index()
    return idx.get(_normalize(name))
