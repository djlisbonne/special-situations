from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import ChatMessageOut, ChatRequest, ChatResponse, Citation
from app.config import get_settings
from app.db.models import ChatMessage, Event
from app.db.session import get_db
from app.llm.client import _fallback_extract_text, extract_json, get_openai
from app.llm.prompts import CHAT_SYSTEM

router = APIRouter(prefix="/events", tags=["chat"])


def _serialize(msg: ChatMessage) -> ChatMessageOut:
    cits = []
    if isinstance(msg.citations, list):
        cits = [Citation(**c) for c in msg.citations]
    elif isinstance(msg.citations, dict) and "citations" in msg.citations:
        cits = [Citation(**c) for c in msg.citations["citations"]]
    return ChatMessageOut(
        id=msg.id,
        role=msg.role,
        content=msg.content,
        citations=cits,
        created_at=msg.created_at,
    )


@router.post("/{event_id}/chat", response_model=ChatResponse)
def chat(event_id: int, body: ChatRequest, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).one_or_none()
    if not event:
        raise HTTPException(404, "event not found")

    user_msg = ChatMessage(event_id=event.id, role="user", content=body.question)
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    history = (
        db.query(ChatMessage)
        .filter(ChatMessage.event_id == event.id)
        .order_by(ChatMessage.created_at)
        .all()
    )

    # The filing goes in `instructions` (the Responses API's system slot).
    # gpt-4o's 128k context handles a 120k-char filing cleanly there, which
    # keeps the multi-turn `input` array as clean alternating user/assistant
    # messages.
    filing_text = (event.filing.raw_text or "")[:120_000]
    system_msg = (
        CHAT_SYSTEM
        + "\n\n"
        + f'<filing form_type="{event.filing.form_type}" '
        + f'company="{event.filing.company_name}" '
        + f'accession="{event.filing.accession_number}">\n'
        + filing_text
        + "\n</filing>"
    )

    # ChatMessage.role is already "user" or "assistant"
    conversation: list[dict] = [
        {"role": m.role, "content": m.content} for m in history
    ]

    # OpenAI's `text.format=json_object` requires the word "json" in input,
    # not just instructions. Append a small primer to the most recent user
    # message — ephemeral, not persisted in chat history.
    for msg in reversed(conversation):
        if msg["role"] == "user":
            msg["content"] = (
                msg["content"]
                + "\n\n(Respond with a single JSON object per the schema in instructions.)"
            )
            break

    settings = get_settings()
    client = get_openai()
    resp = client.responses.create(
        model=settings.openai_model_primary,
        instructions=system_msg,
        input=conversation,
        max_output_tokens=1500,
        text={"format": {"type": "json_object"}},
    )
    text = (getattr(resp, "output_text", None) or "").strip()
    if not text:
        text = _fallback_extract_text(resp)
    try:
        data = json.loads(text)
        answer = data.get("answer", "")
        citations = data.get("citations", [])
    except json.JSONDecodeError:
        try:
            data = extract_json(text)
            answer = data.get("answer", "")
            citations = data.get("citations", [])
        except ValueError:
            answer, citations = text, []

    asst = ChatMessage(
        event_id=event.id,
        role="assistant",
        content=answer,
        citations=citations,
    )
    db.add(asst)
    db.commit()
    db.refresh(asst)

    return ChatResponse(user_message=_serialize(user_msg), assistant_message=_serialize(asst))


@router.get("/{event_id}/chat", response_model=list[ChatMessageOut])
def list_chat(event_id: int, db: Session = Depends(get_db)):
    event = db.query(Event).filter(Event.id == event_id).one_or_none()
    if not event:
        raise HTTPException(404, "event not found")
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.event_id == event.id)
        .order_by(ChatMessage.created_at)
        .all()
    )
    return [_serialize(r) for r in rows]
