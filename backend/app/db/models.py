from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class EventType(str, enum.Enum):
    SPINOFF = "spinoff"
    SPLITOFF = "splitoff"
    STUB = "stub"
    RIGHTS_OFFERING = "rights_offering"
    POST_BANKRUPTCY = "post_bankruptcy"
    RECAP = "recapitalization"
    MERGER_SECURITY = "merger_security"
    INSIDER_CLUSTER = "insider_cluster"
    ACTIVIST_13D = "activist_13d"
    UNKNOWN = "unknown"


class EventStatus(str, enum.Enum):
    ANNOUNCED = "announced"
    EFFECTIVE = "effective"
    COMPLETED = "completed"
    WITHDRAWN = "withdrawn"


class Filing(Base):
    __tablename__ = "filings"
    __table_args__ = (
        UniqueConstraint("accession_number", name="uq_filings_accession"),
        Index("ix_filings_cik_form", "cik", "form_type"),
        Index("ix_filings_filed_at", "filed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    accession_number: Mapped[str] = mapped_column(String(32), nullable=False)
    cik: Mapped[str] = mapped_column(String(16), nullable=False)
    company_name: Mapped[str] = mapped_column(String(256), nullable=False)
    form_type: Mapped[str] = mapped_column(String(32), nullable=False)
    filed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    primary_doc_url: Mapped[str] = mapped_column(String(512), nullable=False)
    index_url: Mapped[str] = mapped_column(String(512), nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    events: Mapped[list[Event]] = relationship(
        "Event", back_populates="filing", cascade="all, delete-orphan"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_type_status", "event_type", "status"),
        Index("ix_events_score", "composite_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id", ondelete="CASCADE"))
    event_type: Mapped[EventType] = mapped_column(Enum(EventType), nullable=False)
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus), default=EventStatus.ANNOUNCED, nullable=False
    )

    # Parties
    parent_cik: Mapped[str | None] = mapped_column(String(16))
    parent_name: Mapped[str | None] = mapped_column(String(256))
    parent_ticker: Mapped[str | None] = mapped_column(String(16))
    spinco_name: Mapped[str | None] = mapped_column(String(256))
    spinco_ticker: Mapped[str | None] = mapped_column(String(16))

    # Spin-off specifics
    distribution_ratio: Mapped[str | None] = mapped_column(String(64))
    record_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    distribution_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_ticker_listing: Mapped[str | None] = mapped_column(String(64))

    # LLM-derived summary
    headline: Mapped[str | None] = mapped_column(String(512))
    thesis: Mapped[str | None] = mapped_column(Text)
    rationale_stated: Mapped[str | None] = mapped_column(Text)

    # Greenblatt scoring (0-10 each)
    score_insider_alignment: Mapped[float | None] = mapped_column(Float)
    score_forced_selling: Mapped[float | None] = mapped_column(Float)
    score_hidden_value: Mapped[float | None] = mapped_column(Float)
    score_leverage_profile: Mapped[float | None] = mapped_column(Float)
    score_information_asymmetry: Mapped[float | None] = mapped_column(Float)
    composite_score: Mapped[float | None] = mapped_column(Float)

    score_rationale: Mapped[dict | None] = mapped_column(JSON)  # per-axis explanation + citations
    flags: Mapped[dict | None] = mapped_column(JSON)  # warnings, missing data, etc.

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    filing: Mapped[Filing] = relationship("Filing", back_populates="events")
    messages: Mapped[list[ChatMessage]] = relationship(
        "ChatMessage", back_populates="event", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user|assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    event: Mapped[Event] = relationship("Event", back_populates="messages")


class OutcomeSnapshot(Base):
    """Cached post-spin performance report + LLM corroboration for one event.

    The factual report is cheap-ish but rate-limited (market API), and the
    corroboration is an LLM call, so we persist the latest computation and let
    the API decide when it's stale enough to recompute.
    """

    __tablename__ = "outcome_snapshots"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_outcome_event"),
        Index("ix_outcome_computed_at", "computed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    as_of: Mapped[str | None] = mapped_column(String(16))  # YYYY-MM-DD the report covers
    phase: Mapped[str | None] = mapped_column(String(32))
    report: Mapped[dict | None] = mapped_column(JSON)  # factual price-action report
    corroboration: Mapped[dict | None] = mapped_column(JSON)  # LLM verdict

    event: Mapped[Event] = relationship("Event")


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filings_seen: Mapped[int] = mapped_column(Integer, default=0)
    events_created: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)


def init_db() -> None:
    from app.db.session import engine

    Base.metadata.create_all(engine)
