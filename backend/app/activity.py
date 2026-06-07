"""In-process activity bus.

Pipeline code calls `bus().emit(level, stage, message, **details)` at every
meaningful step. Subscribers (the SSE endpoint) get every emit pushed to their
queue. A small ring buffer remembers the last N events so a panel that mounts
mid-scan can backfill recent history.

The bus is thread-safe: `emit()` can be called from `asyncio.to_thread()` and
will hop back to the main event loop via `call_soon_threadsafe`.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class ActivityEvent:
    ts: str
    level: str  # info | success | warn | error
    stage: str  # e.g. "scan.start", "edgar.fetch", "llm.extract", "scan.done"
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    scan_run_id: int | None = None


class ActivityBus:
    def __init__(self, ring_size: int = 250):
        self.subscribers: list[asyncio.Queue[ActivityEvent]] = []
        self.ring: deque[ActivityEvent] = deque(maxlen=ring_size)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def emit(
        self,
        level: str,
        stage: str,
        message: str,
        *,
        scan_run_id: int | None = None,
        **details: Any,
    ) -> None:
        ev = ActivityEvent(
            ts=datetime.now(timezone.utc).isoformat(),
            level=level,
            stage=stage,
            message=message,
            details=details or {},
            scan_run_id=scan_run_id,
        )
        self.ring.append(ev)
        log.info("[%s] %s: %s", level, stage, message)
        loop = self._loop
        for q in list(self.subscribers):
            if loop is not None and loop.is_running():
                try:
                    loop.call_soon_threadsafe(self._safe_put, q, ev)
                except RuntimeError:
                    pass
            else:
                self._safe_put(q, ev)

    @staticmethod
    def _safe_put(q: asyncio.Queue[ActivityEvent], ev: ActivityEvent) -> None:
        try:
            q.put_nowait(ev)
        except asyncio.QueueFull:
            # Drop oldest to make room; activity is informational.
            try:
                _ = q.get_nowait()
                q.put_nowait(ev)
            except Exception:
                pass

    async def subscribe(self) -> asyncio.Queue[ActivityEvent]:
        q: asyncio.Queue[ActivityEvent] = asyncio.Queue(maxsize=200)
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[ActivityEvent]) -> None:
        try:
            self.subscribers.remove(q)
        except ValueError:
            pass

    def recent(self, limit: int = 100, scan_run_id: int | None = None) -> list[ActivityEvent]:
        items = list(self.ring)
        if scan_run_id is not None:
            items = [e for e in items if e.scan_run_id == scan_run_id]
        return items[-limit:]


_bus = ActivityBus()


def bus() -> ActivityBus:
    return _bus


def to_dict(ev: ActivityEvent) -> dict[str, Any]:
    return asdict(ev)
