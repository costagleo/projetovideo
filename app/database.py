from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
import os

from app.config import get_settings

settings = get_settings()

os.makedirs(os.path.dirname(settings.DB_PATH), exist_ok=True)

engine = create_engine(
    f"sqlite:///{settings.DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _migrate_invites_email_to_name()


def _migrate_invites_email_to_name():
    """Rename invites.email column to invites.name if needed."""
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(invites)"))
        columns = [row[1] for row in result]
        if "email" in columns and "name" not in columns:
            conn.execute(text("ALTER TABLE invites RENAME COLUMN email TO name"))
            conn.commit()
