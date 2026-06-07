from __future__ import annotations

from datetime import datetime
from typing import Any

from app.config import get_settings
from app.llm.client import json_chat
from app.llm.prompts import EXTRACTOR_SYSTEM, SCORER_SYSTEM


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None


def extract_spinoff_fields(filing_text: str) -> dict[str, Any]:
    """Pull structured spin-off fields from a Form 10-12B information statement."""
    settings = get_settings()
    # Information statements run long; pass a large but bounded slice.
    excerpt = filing_text[:120_000]
    data = json_chat(
        model=settings.openai_model_primary,
        system=EXTRACTOR_SYSTEM,
        user=excerpt,
        max_tokens=2000,
    )
    data["_record_date_dt"] = _parse_date(data.get("record_date"))
    data["_distribution_date_dt"] = _parse_date(data.get("distribution_date"))
    return data


def score_spinoff(filing_text: str, extracted: dict[str, Any]) -> dict[str, Any]:
    """Run the Greenblatt scoring pass over the spin-off."""
    settings = get_settings()
    excerpt = filing_text[:120_000]
    summary_block = (
        f"Extracted fields (from prior pass):\n"
        f"  parent_name: {extracted.get('parent_name')}\n"
        f"  spinco_name: {extracted.get('spinco_name')}\n"
        f"  distribution_ratio: {extracted.get('distribution_ratio')}\n"
        f"  stated_rationale: {extracted.get('stated_rationale')}\n"
        f"  spinco_industry: {extracted.get('spinco_industry')}\n"
        f"  insider_ownership_pct: {extracted.get('insider_ownership_pct')}\n"
        f"  spinco_debt_usd: {extracted.get('spinco_debt_usd')}\n"
        f"  spinco_ebitda_usd: {extracted.get('spinco_ebitda_usd')}\n"
        f"  key_risks: {extracted.get('key_risks')}\n"
    )
    user_msg = summary_block + "\n\nFiling text:\n\n" + excerpt
    return json_chat(
        model=settings.openai_model_primary,
        system=SCORER_SYSTEM,
        user=user_msg,
        max_tokens=3000,
    )
