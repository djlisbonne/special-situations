from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.activity import bus, to_dict

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("/recent")
def recent(
    limit: int = Query(100, ge=1, le=250),
    scan_run_id: int | None = Query(None),
):
    return [to_dict(e) for e in bus().recent(limit=limit, scan_run_id=scan_run_id)]


@router.get("/stream")
async def stream(scan_run_id: int | None = Query(None)):
    """Server-Sent Events stream of activity events.

    Each event is `data: <json>\\n\\n`. Frontend uses native EventSource.
    """
    q = await bus().subscribe()

    async def gen():
        # Initial heartbeat lets the client know the stream is open.
        yield 'event: open\ndata: {"ok":true}\n\n'
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    # SSE keepalive comment so proxies don't drop us.
                    yield ": ping\n\n"
                    continue
                if scan_run_id is not None and ev.scan_run_id not in (None, scan_run_id):
                    continue
                yield f"data: {json.dumps(to_dict(ev))}\n\n"
        finally:
            bus().unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
