import json
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def now():
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class Study(Base):
    __tablename__ = "configured_studies"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String, default="")
    category: Mapped[str] = mapped_column(String, default="")
    side: Mapped[str] = mapped_column(String, default="both")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    title: Mapped[str] = mapped_column(String, default="")
    fetched: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Chapter(Base):
    __tablename__ = "study_chapters"
    id: Mapped[str] = mapped_column(
        String, primary_key=True
    )  # study/chapter, avoids ID collision
    study_id: Mapped[str] = mapped_column(
        ForeignKey("configured_studies.id", ondelete="CASCADE")
    )
    remote_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    base: Mapped[str] = mapped_column(Text)
    local: Mapped[str] = mapped_column(Text)
    remote: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="synced")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched: Mapped[str] = mapped_column(String, default=now)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    undo: Mapped[str] = mapped_column(Text, default="[]")
    redo: Mapped[str] = mapped_column(Text, default="[]")


class Snapshot(Base):
    __tablename__ = "chapter_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("study_chapters.id", ondelete="CASCADE")
    )
    pgn: Mapped[str] = mapped_column(Text)
    hash: Mapped[str] = mapped_column(String)
    created: Mapped[str] = mapped_column(String, default=now)


class Position(Base):
    __tablename__ = "positions"
    key: Mapped[str] = mapped_column(String, primary_key=True)


class Occurrence(Base):
    __tablename__ = "position_occurrences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(ForeignKey("positions.key"))
    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("study_chapters.id", ondelete="CASCADE")
    )
    path: Mapped[str] = mapped_column(Text)
    fen: Mapped[str] = mapped_column(String)
    san: Mapped[str] = mapped_column(String)
    comment: Mapped[str] = mapped_column(Text)
    nags: Mapped[str] = mapped_column(Text)
    continuations: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        Index("ix_occurrence_position", "key"),
        Index("ix_occurrence_chapter", "chapter_id"),
    )


class Backup(Base):
    __tablename__ = "sync_backups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("study_chapters.id", ondelete="CASCADE")
    )
    pgn: Mapped[str] = mapped_column(Text)
    created: Mapped[str] = mapped_column(String, default=now)


class Operation(Base):
    __tablename__ = "sync_operations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)
    detail: Mapped[str] = mapped_column(Text, default="")
    created: Mapped[str] = mapped_column(String, default=now)


class Training(Base):
    __tablename__ = "training_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("study_chapters.id", ondelete="CASCADE")
    )
    path: Mapped[str] = mapped_column(Text)
    correct: Mapped[bool] = mapped_column(Boolean)
    interval: Mapped[int] = mapped_column(Integer)
    due: Mapped[str] = mapped_column(String)
    created: Mapped[str] = mapped_column(String, default=now)


def database(path):
    engine = create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def pragmas(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")

    from .migrations import migrate

    migrate(engine, Base.metadata)
    return sessionmaker(engine, expire_on_commit=False)


def study_json(s):
    return {
        k: getattr(s, k)
        for k in (
            "id",
            "label",
            "category",
            "side",
            "enabled",
            "title",
            "fetched",
            "error",
        )
    }


def chapter_json(c, content=False):
    result = {
        k: getattr(c, k)
        for k in (
            "id",
            "study_id",
            "remote_id",
            "name",
            "status",
            "fetched",
            "error",
            "deleted",
        )
    }
    result.update(can_undo=bool(json.loads(c.undo)), can_redo=bool(json.loads(c.redo)))
    if content:
        from .pgn import one, tree

        game = one(c.local)
        result.update(pgn=c.local, tags=dict(game.headers), nodes=tree(game))
    return result
