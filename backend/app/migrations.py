"""Versioned, transactional initial schema migration for SQLite."""

from sqlalchemy import text


def migrate(engine, metadata):
    with engine.begin() as connection:
        version = connection.execute(text("PRAGMA user_version")).scalar()
        if version not in (0, 1):
            raise RuntimeError("Database schema is newer than this application")
        if version == 0:
            metadata.create_all(connection)
            connection.execute(text("PRAGMA user_version=1"))
