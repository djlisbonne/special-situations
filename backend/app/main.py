import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.activity import bus
from app.api import activity, chat, events, performance, scan
from app.db.models import init_db
from app.scheduler.jobs import start_scheduler, stop_scheduler
from app.web import views as web_views


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    bus().bind_loop(asyncio.get_running_loop())
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Greenblatt", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# JSON API lives under /api so the root namespace is free for the
# server-rendered UI (e.g. GET /events/{id} returns an HTML page, while
# GET /api/events/{id} returns JSON).
API_PREFIX = "/api"
app.include_router(events.router, prefix=API_PREFIX)
app.include_router(scan.router, prefix=API_PREFIX)
app.include_router(chat.router, prefix=API_PREFIX)
app.include_router(activity.router, prefix=API_PREFIX)
app.include_router(performance.router, prefix=API_PREFIX)

# Server-rendered UI at the root.
app.include_router(web_views.router)

_STATIC_DIR = Path(__file__).parent / "web" / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/health")
def health():
    return {"ok": True}
