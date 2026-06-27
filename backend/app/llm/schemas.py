from __future__ import annotations

from typing import Any


JsonSchema = dict[str, Any]

EVENT_TYPES = [
    "spinoff",
    "splitoff",
    "stub",
    "rights_offering",
    "post_bankruptcy",
    "recapitalization",
    "merger_security",
    "insider_cluster",
    "activist_13d",
    "unknown",
]

SPINOFF_FIELDS = [
    "parent_name",
    "parent_ticker",
    "spinco_name",
    "expected_ticker_listing",
    "distribution_ratio",
    "record_date",
    "distribution_date",
    "stated_rationale",
    "spinco_industry",
    "spinco_revenue_usd",
    "spinco_ebitda_usd",
    "spinco_debt_usd",
    "insider_ownership_pct",
    "management_incentive_plan",
    "key_risks",
]

RAW_VALUE_FIELDS = [
    "distribution_ratio",
    "record_date",
    "distribution_date",
    "spinco_revenue_usd",
    "spinco_ebitda_usd",
    "spinco_debt_usd",
    "insider_ownership_pct",
]

AXES = [
    "insider_alignment",
    "forced_selling",
    "hidden_value",
    "leverage_profile",
    "information_asymmetry",
]


def _string(description: str = "") -> JsonSchema:
    out: JsonSchema = {"type": "string"}
    if description:
        out["description"] = description
    return out


def _nullable_string(description: str = "") -> JsonSchema:
    out: JsonSchema = {"type": ["string", "null"]}
    if description:
        out["description"] = description
    return out


def _nullable_number(description: str = "") -> JsonSchema:
    out: JsonSchema = {"type": ["number", "null"]}
    if description:
        out["description"] = description
    return out


def _string_array(description: str = "") -> JsonSchema:
    out: JsonSchema = {"type": "array", "items": _string()}
    if description:
        out["description"] = description
    return out


def _object(properties: dict[str, JsonSchema]) -> JsonSchema:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties.keys()),
        "additionalProperties": False,
    }


def _field_enum_array(description: str = "") -> JsonSchema:
    out: JsonSchema = {
        "type": "array",
        "items": {"type": "string", "enum": SPINOFF_FIELDS},
    }
    if description:
        out["description"] = description
    return out


EVENT_CLASSIFICATION_SCHEMA: JsonSchema = {
    "name": "EventClassification",
    "description": "Classifies one SEC filing into a special-situation event type.",
    "strict": True,
    "schema": _object(
        {
            "event_type": {"type": "string", "enum": EVENT_TYPES},
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Confidence that the event type is correct.",
            },
            "reasoning": _string("One concise sentence explaining the classification."),
            "evidence_quote": _nullable_string(
                "Short verbatim filing quote supporting the classification, or null."
            ),
        }
    ),
}


SPINOFF_EXTRACTION_SCHEMA: JsonSchema = {
    "name": "SpinoffExtraction",
    "description": "Extracts spin-off fields with evidence and missing-data metadata.",
    "strict": True,
    "schema": _object(
        {
            "parent_name": _nullable_string(),
            "parent_ticker": _nullable_string(),
            "spinco_name": _nullable_string(),
            "expected_ticker_listing": _nullable_string(),
            "distribution_ratio": _nullable_string(),
            "record_date": {
                "type": ["string", "null"],
                "format": "date",
                "description": "Normalized YYYY-MM-DD date when unambiguous, else null.",
            },
            "distribution_date": {
                "type": ["string", "null"],
                "format": "date",
                "description": "Normalized YYYY-MM-DD date when unambiguous, else null.",
            },
            "stated_rationale": _nullable_string(),
            "spinco_industry": _nullable_string(),
            "spinco_revenue_usd": _nullable_number(),
            "spinco_ebitda_usd": _nullable_number(),
            "spinco_debt_usd": _nullable_number(),
            "insider_ownership_pct": _nullable_number(
                "Post-spin SpinCo insider ownership as a percentage, not decimal."
            ),
            "management_incentive_plan": _nullable_string(),
            "key_risks": _string_array("Top disclosed risks, empty when not found."),
            "raw_values": _object(
                {
                    name: _nullable_string("Raw source text before normalization.")
                    for name in RAW_VALUE_FIELDS
                }
            ),
            "evidence": _object(
                {
                    name: _nullable_string(
                        "Short verbatim filing quote supporting this field when non-null."
                    )
                    for name in SPINOFF_FIELDS
                }
            ),
            "inferred_fields": _field_enum_array(
                "Fields whose values are inferred rather than explicitly stated."
            ),
            "missing_fields": _field_enum_array(
                "Important requested fields absent from the filing."
            ),
        }
    ),
}


AXIS_ANALYSIS_SCHEMA = _object(
    {
        "score": {
            "type": "number",
            "minimum": 0,
            "maximum": 10,
            "description": "Opportunity score for this axis.",
        },
        "rationale": _string("Two to three sentences explaining the calibrated score."),
        "positive_evidence": _string_array(
            "Short verbatim quotes that strengthen this axis score."
        ),
        "negative_evidence": _string_array(
            "Short verbatim quotes or disclosed facts that weaken this axis score."
        ),
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Confidence in this axis analysis.",
        },
    }
)

SPINOFF_SCORE_SCHEMA: JsonSchema = {
    "name": "SpinoffScore",
    "description": "Scores a spin-off across Greenblatt axes without computing composite.",
    "strict": True,
    "schema": _object(
        {
            "headline": _string("Single sentence, no more than 120 characters."),
            "thesis": _string("Three to five sentences summarizing opportunity and risks."),
            "axes": _object({axis: AXIS_ANALYSIS_SCHEMA for axis in AXES}),
            "flags": _object(
                {
                    "missing_financials": {"type": "boolean"},
                    "no_insider_ownership_disclosed": {"type": "boolean"},
                    "spinco_appears_distressed": {"type": "boolean"},
                    "notes": _string_array("Other missing-data or risk flags."),
                }
            ),
        }
    ),
}

_AXIS_OUTCOME = _object(
    {
        "status": {
            "type": "string",
            "enum": ["confirmed", "contradicted", "not_yet_testable"],
            "description": "Whether realized price action so far supports, refutes, "
            "or cannot yet test this axis of the original thesis.",
        },
        "note": _string("One sentence tying the price action to this axis."),
    }
)

THESIS_CORROBORATION_SCHEMA: JsonSchema = {
    "name": "ThesisCorroboration",
    "description": (
        "Judges whether a spin-off thesis played out against realized price "
        "action. Grounded ONLY in the supplied scores, thesis, and price "
        "statistics — never invent prices or news."
    ),
    "strict": True,
    "schema": _object(
        {
            "verdict": {
                "type": "string",
                "enum": ["validated", "partially_validated", "invalidated", "too_early"],
                "description": "Overall judgement of the thesis vs. what the market did.",
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "summary": _string(
                "Three to five sentences: what was predicted, what happened, and the gap."
            ),
            "drivers": _string_array(
                "The forces that actually moved the price (anticipation re-rating, "
                "sector beta, forced-selling washout, fundamentals, multiple "
                "re-rating, macro). Attribute alpha vs. beta explicitly."
            ),
            "axis_assessment": _object({axis: _AXIS_OUTCOME for axis in AXES}),
            "what_to_watch": _string_array(
                "Forward-looking catalysts or dates a fund should monitor next."
            ),
        }
    ),
}

CHAT_ANSWER_SCHEMA: JsonSchema = {
    "name": "ChatAnswer",
    "description": "Answers a filing-grounded question with citations and limitations.",
    "strict": True,
    "schema": _object(
        {
            "answer": _string("Markdown answer with inline citation markers like [Q1]."),
            "answered_from_filing": {
                "type": "boolean",
                "description": "True only when the filing contains enough support to answer.",
            },
            "citations": {
                "type": "array",
                "items": _object(
                    {
                        "id": _string("Citation marker such as Q1."),
                        "quote": _string("Short verbatim quote from the filing."),
                    }
                ),
            },
            "limitations": _string_array(
                "Facts not found in the filing or scope limits of the answer."
            ),
        }
    ),
}
