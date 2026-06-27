from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()

# Dialect-aware engine. Postgres is the default for dev/server deployments;
# SQLite is the low-footprint option for tiny hosts (e.g. a 1 GB Raspberry Pi),
# where dropping a separate Postgres process matters. The app uses no
# Postgres-specific column types, so JSON/Enum/DateTime all map cleanly.
_url = settings.database_url
_is_sqlite = _url.startswith("sqlite")

_connect_args: dict = {}
if _is_sqlite:
    # FastAPI runs sync endpoints across a thread pool; SQLite's default
    # same-thread guard would reject those connections.
    _connect_args["check_same_thread"] = False

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
