"""SQLite persistence for things that are naturally tabular: provider calls (cost) and jobs.

Creative artifacts (plans, prompts, images, reviews) live on the filesystem inside the project
directory so they are inspectable, diffable and survive without the database.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ProviderCall(Base):
    __tablename__ = "provider_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    stage: Mapped[str] = mapped_column(String(64), index=True)
    scene_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    operation: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    units: Mapped[float] = mapped_column(Float, default=0.0)
    unit_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    generation_count: Mapped[int] = mapped_column(Integer, default=1)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    regeneration: Mapped[bool] = mapped_column(Boolean, default=False)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow,
                                                 onupdate=_utcnow)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    scene_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # QUEUED -> GENERATING -> DOWNLOADING -> REVIEWING -> COMPLETE | FAILED
    status: Mapped[str] = mapped_column(String(32), default="QUEUED")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{path}", connect_args={"check_same_thread": False}, future=True
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)


_databases: dict[Path, Database] = {}
_lock = threading.Lock()


def get_database(path: Path) -> Database:
    path = path.resolve()
    with _lock:
        if path not in _databases:
            _databases[path] = Database(path)
        return _databases[path]
