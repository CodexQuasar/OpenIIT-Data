"""Database session management."""

from contextlib import contextmanager
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from config.settings import get_settings
from data.models import Base

_settings = get_settings()

_engine = create_engine(
    _settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in _settings.database_url else {},
    poolclass=StaticPool if "sqlite" in _settings.database_url else None,
    echo=_settings.environment == "development",
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def init_db() -> None:
    """Initialize database tables."""
    Base.metadata.create_all(bind=_engine)
    if "sqlite" in _settings.database_url:
        inspector = inspect(_engine)
        migrations = {
            "accounts": {
                "location_crs": "VARCHAR(32)",
                "confirmed_latitude": "FLOAT",
                "confirmed_longitude": "FLOAT",
                "confirmed_radius_m": "FLOAT",
                "confirmed_at": "DATETIME",
                "predicted_latitude": "FLOAT",
                "predicted_longitude": "FLOAT",
                "predicted_radius_m": "FLOAT",
                "predicted_at": "DATETIME",
            },
            "visits": {
                "remark_correction": "TEXT",
                "coordinate_crs": "VARCHAR(32)",
            },
        }
        with _engine.begin() as connection:
            for table, columns in migrations.items():
                existing = {column["name"] for column in inspector.get_columns(table)}
                for name, sql_type in columns.items():
                    if name not in existing:
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))


def get_db() -> Session:
    """Get database session (for FastAPI dependency)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Session:
    """Context manager for database sessions."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()