from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()

# SQLite is the default (single file, no server process — sized for an
# always-on 1 GB Raspberry Pi). Any SQLAlchemy URL still works via
# DATABASE_URL; the app uses no dialect-specific column types.
_url = settings.database_url
_is_sqlite = _url.startswith("sqlite")

_connect_args: dict = {}
if _is_sqlite:
    # FastAPI runs sync endpoints across a thread pool; SQLite's default
    # same-thread guard would reject those connections.
    _connect_args["check_same_thread"] = False
    # Create the parent directory so the default ./data/... path works on a
    # fresh checkout without a manual mkdir.
    if _url.startswith("sqlite:///"):
        _db_path = _url.removeprefix("sqlite:///")
        if _db_path and _db_path != ":memory:":
            Path(_db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    _url, pool_pre_ping=True, future=True, connect_args=_connect_args
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver glue
        cur = dbapi_conn.cursor()
        # WAL lets the nightly scan write while the UI reads; busy_timeout rides
        # out the brief lock instead of erroring with "database is locked".
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
