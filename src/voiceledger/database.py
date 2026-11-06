from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import JSON, Boolean, Float, Integer, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def uid() -> str:
    return str(uuid.uuid4())


def now() -> str:
    return datetime.now(UTC).isoformat()


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=now)


class Recording(Base):
    __tablename__ = "recordings"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String, index=True)
    filename: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String)
    original_path: Mapped[str] = mapped_column(String)
    metadata_json: Mapped[dict] = mapped_column(JSON)
    current_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String, default=now)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    recording_id: Mapped[str] = mapped_column(String, index=True)
    mode: Mapped[str] = mapped_column(String)
    language: Mapped[str] = mapped_column(String, default="bg")
    kind: Mapped[str] = mapped_column(String, default="process")
    status: Mapped[str] = mapped_column(String, default="queued")
    stage: Mapped[str] = mapped_column(String, default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_rows: Mapped[list] = mapped_column(JSON, default=list)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=now)
    updated_at: Mapped[str] = mapped_column(String, default=now)


class Speaker(Base):
    __tablename__ = "speakers"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    notes: Mapped[str] = mapped_column(String, default="")


class Sample(Base):
    __tablename__ = "samples"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    speaker_id: Mapped[str] = mapped_column(String, index=True)
    recording_id: Mapped[str] = mapped_column(String, index=True)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    model_revision: Mapped[str | None] = mapped_column(String, nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)


class Correction(Base):
    __tablename__ = "corrections"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    recording_id: Mapped[str] = mapped_column(String, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    actions: Mapped[list] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    explanation: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[str] = mapped_column(String, default=now)


class Proposal(Base):
    __tablename__ = "proposals"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    recording_id: Mapped[str] = mapped_column(String, index=True)
    base_revision: Mapped[int] = mapped_column(Integer)
    actions: Mapped[list] = mapped_column(JSON)
    explanation: Mapped[str] = mapped_column(String)
    clarification: Mapped[str | None] = mapped_column(String, nullable=True)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String, default=now)


def database(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{(root / 'voiceledger.sqlite').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def configure(connection, record):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")

    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect, text

    database_path = root / "voiceledger.sqlite"
    with engine.connect() as connection:
        tables = inspect(connection).get_table_names()
        current = (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            if "alembic_version" in tables
            else None
        )
    if tables and current != ScriptDirectory.from_config(config).get_current_head():
        import sqlite3

        backups = root / "backups"
        backups.mkdir(exist_ok=True)
        target = backups / f"before-migration-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}.sqlite"
        with sqlite3.connect(database_path) as source, sqlite3.connect(target) as backup:
            source.backup(backup)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    return sessionmaker(engine, expire_on_commit=False), engine


def serialize(obj, exclude=()):
    return {
        column.name: getattr(obj, column.name)
        for column in obj.__table__.columns
        if column.name not in exclude
    }
