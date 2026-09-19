import os
import threading
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./dining.db")

# Connection pool tuning so the app can serve many concurrent requests.
DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "80"))
DB_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", "70"))
DB_POOL_RECYCLE = int(os.environ.get("DB_POOL_RECYCLE", "3600"))
DB_POOL_TIMEOUT = int(os.environ.get("DB_POOL_TIMEOUT", "30"))

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        pool_size=DB_POOL_SIZE,
        max_overflow=DB_MAX_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=DB_POOL_RECYCLE,
        pool_timeout=DB_POOL_TIMEOUT,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

_sqlite_lock = threading.Lock()

def acquire_app_lock(db, key):
    """PostgreSQL advisory lock (session-scoped). SQLite dev fallback: in-process lock.
    Returns a token to pass to release_app_lock(), or None if the lock is already held."""
    if DATABASE_URL.startswith("postgres"):
        from sqlalchemy import text
        try:
            conn = db.connection()
            acquired = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar()
            return (conn, key) if acquired else None
        except Exception:
            return None
    else:
        if _sqlite_lock.acquire(blocking=False):
            return _sqlite_lock
        return None

def release_app_lock(token):
    if token is None:
        return
    if isinstance(token, tuple):
        conn, key = token
        try:
            from sqlalchemy import text
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
        except Exception:
            pass
    else:
        try:
            token.release()
        except Exception:
            pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
