from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class FilingOut(BaseModel):
    id: int
    accession_number: str
    cik: str
    company_name: str
    form_type: str
    filed_at: datetime
    primary_doc_url: str
    index_url: str

    class Config:
        from_attributes = True


class EventSummary(BaseModel):
    id: int
    event_type: str
    status: str
    parent_name: str | None
    parent_ticker: str | None
    spinco_name: str | None
    spinco_ticker: str | None
    distribution_ratio: str | None
    record_date: datetime | None
    distribution_date: datetime | None
    headline: str | None
    composite_score: float | None
    filed_at: datetime
    accession_number: str

    class Config:
        from_attributes = True


class AxisScore(BaseModel):
    score: float | None = None
    rationale: str | None = None
    citations: list[str] = []


class EventDetail(BaseModel):
    id: int
    event_type: str
    status: str
    parent_cik: str | None
    parent_name: str | None
    parent_ticker: str | None
    spinco_name: str | None
    spinco_ticker: str | None
    distribution_ratio: str | None
    record_date: datetime | None
    distribution_date: datetime | None
    headline: str | None
    thesis: str | None
    rationale_stated: str | None
    composite_score: float | None
    scores: dict[str, AxisScore]
    flags: dict
    filing: FilingOut
    parent_snapshot: dict | None = None
    spinco_snapshot: dict | None = None


class ChatRequest(BaseModel):
    question: str


class Citation(BaseModel):
    id: str
    quote: str


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    citations: list[Citation] = []
    created_at: datetime

    class Config:
        from_attributes = True


class ChatResponse(BaseModel):
    user_message: ChatMessageOut
    assistant_message: ChatMessageOut


class ScanResponse(BaseModel):
    filings_seen: int
    events_created: int
