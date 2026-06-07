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
from app.llm.schemas import JsonSchema

log = logging.getLogger(__name__)


def get_openai() -> OpenAI:
    s = get_settings()
    kwargs: dict[str, Any] = {"api_key": s.openai_api_key}
    if s.openai_base_url:
        kwargs["base_url"] = s.openai_base_url
    if s.openai_organization:
        kwargs["organization"] = s.openai_organization
    return OpenAI(**kwargs)


def structured_chat(
    *,
    model: str,
    system: str,
    input_data: str | list[dict[str, str]],
    schema: JsonSchema,
    max_tokens: int = 2000,
) -> dict[str, Any]:
    """One-shot call that returns parsed Structured Outputs JSON."""
    client = get_openai()
    resp = client.responses.create(
        model=model,
        instructions=system,
        input=input_data,
        max_output_tokens=max_tokens,
        text={"format": _schema_format(schema)},
    )
    refusal = _fallback_extract_refusal(resp)
    if refusal:
        raise ValueError(f"Model refused structured response: {refusal}")
    text = (getattr(resp, "output_text", None) or "").strip()
    if not text:
        text = _fallback_extract_text(resp)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return extract_json(text)


def _schema_format(schema: JsonSchema) -> JsonSchema:
    return {
        "type": "json_schema",
        "name": schema["name"],
        "description": schema.get("description", ""),
        "schema": schema["schema"],
        "strict": schema.get("strict", True),
    }


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


def _fallback_extract_refusal(resp: Any) -> str:
    """Return refusal text from Responses output items, if present."""
    for item in getattr(resp, "output", []) or []:
        for c in getattr(item, "content", []) or []:
            refusal = getattr(c, "refusal", None)
            if isinstance(refusal, str) and refusal:
                return refusal
    return ""


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
