"""OpenAI client wrapper for the Responses API.

Uses `client.responses.create()`, which is OpenAI's current preferred path
(the older `chat.completions.create()` works but is on the legacy track).

Key shape differences vs. Chat Completions, captured here so the rest of the
backend doesn't have to think about it:

  Chat Completions                Responses API
  ----------------                -------------
  messages=[{system}, {user}]     instructions=<system>, input=<user or list>
  max_tokens=N                    max_output_tokens=N
  response_format={"type":"..."}  text={"format": {"type": "..."}}
  resp.choices[0].message.content resp.output_text
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from app.config import get_settings

log = logging.getLogger(__name__)


def get_openai() -> OpenAI:
    s = get_settings()
    kwargs: dict[str, Any] = {"api_key": s.openai_api_key}
    if s.openai_base_url:
        kwargs["base_url"] = s.openai_base_url
    if s.openai_organization:
        kwargs["organization"] = s.openai_organization
    return OpenAI(**kwargs)


_JSON_PRIMER = "Respond with a single JSON object as specified in the instructions.\n\n"


def json_chat(
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int = 2000,
) -> dict[str, Any]:
    """One-shot system+user call that returns parsed JSON.

    Uses the Responses API with `text.format=json_object` so the model is
    constrained to emit a valid JSON object. Falls back to a tolerant
    extractor if the model still produces fenced or preamble output.

    Note: OpenAI's `text.format=json_object` requires the literal word "json"
    to appear in the *input* (not just the instructions). We prepend a small
    primer here so callers don't have to think about it.
    """
    client = get_openai()
    resp = client.responses.create(
        model=model,
        instructions=system,
        input=_JSON_PRIMER + user,
        max_output_tokens=max_tokens,
        text={"format": {"type": "json_object"}},
    )
    text = (getattr(resp, "output_text", None) or "").strip()
    if not text:
        # Some SDK versions don't populate output_text aggregator; rummage.
        text = _fallback_extract_text(resp)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return extract_json(text)


def _fallback_extract_text(resp: Any) -> str:
    """Walk the Responses API output items to gather any text content.

    Newer SDKs expose `.output_text` directly. Older / minor variations may
    require walking `.output[*].content[*].text` instead.
    """
    parts: list[str] = []
    for item in getattr(resp, "output", []) or []:
        for c in getattr(item, "content", []) or []:
            t = getattr(c, "text", None)
            if isinstance(t, str):
                parts.append(t)
            elif hasattr(t, "value"):  # OutputText.value on some versions
                parts.append(str(t.value))
    return "".join(parts).strip()


def extract_json(text: str) -> dict[str, Any]:
    """Tolerant JSON extractor for responses that include fences or preamble."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON found in model output: {text[:200]!r}")
    return json.loads(text[start : end + 1])
