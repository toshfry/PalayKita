import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from database.models import Base

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH  = os.path.join(_BASE_DIR, 'instance', 'palaykita.db')
_DB_URL   = f'sqlite:///{_DB_PATH}'

engine       = create_engine(_DB_URL, connect_args={'check_same_thread': False})
SessionLocal = sessionmaker(bind=engine)


def _column_exists(conn, table_name, column_name):
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(row[1] == column_name for row in rows)


def _ensure_sqlite_schema():
    """Add lightweight upgrade columns for existing PalayKita databases."""
    with engine.begin() as conn:
        if not _column_exists(conn, 'settings', 'server_port'):
            conn.execute(text("ALTER TABLE settings ADD COLUMN server_port INTEGER DEFAULT 5000"))


def init_db():
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    Base.metadata.create_all(engine)
    _ensure_sqlite_schema()


def get_session():
    return SessionLocal()
