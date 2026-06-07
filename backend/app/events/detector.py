from __future__ import annotations

from app.config import get_settings
from app.db.models import EventType
from app.llm.client import json_chat
from app.llm.prompts import CLASSIFIER_SYSTEM


# Form-type heuristic: most reliable single signal.
FORM_TO_TYPE: dict[str, EventType] = {
    "10-12B": EventType.SPINOFF,
    "10-12B/A": EventType.SPINOFF,
    "10-12G": EventType.SPINOFF,
    "10-12G/A": EventType.SPINOFF,
}


def classify_by_form(form_type: str) -> EventType | None:
    return FORM_TO_TYPE.get(form_type.upper())


def classify_with_llm(form_type: str, excerpt: str) -> tuple[EventType, float, str]:
    """Fallback / second-pass classifier for ambiguous filings (8-K, 425, etc.)."""
    settings = get_settings()
    user_msg = (
        f"Form type: {form_type}\n\n"
        f"Filing excerpt (first ~12k chars):\n\n{excerpt[:12_000]}"
    )
    data = json_chat(
        model=settings.openai_model_fast,
        system=CLASSIFIER_SYSTEM,
        user=user_msg,
        max_tokens=300,
    )
    try:
        et = EventType(data["event_type"])
    except (ValueError, KeyError):
        et = EventType.UNKNOWN
    return et, float(data.get("confidence", 0.0)), data.get("reasoning", "")
