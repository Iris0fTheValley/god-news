from __future__ import annotations

from pathlib import Path

from sqlalchemy import event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str, *, sqlite_busy_timeout_ms: int = 5_000) -> None:
        self._sqlite_busy_timeout_ms = sqlite_busy_timeout_ms
        self._ensure_sqlite_parent(url)
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_pre_ping=True,
        )
        if make_url(url).drivername.startswith("sqlite"):
            self._configure_sqlite()
        self.sessions = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    def _configure_sqlite(self) -> None:
        @event.listens_for(self.engine.sync_engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
            del connection_record
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute(f"PRAGMA busy_timeout={self._sqlite_busy_timeout_ms}")
                cursor.execute("PRAGMA journal_mode=WAL")
            finally:
                cursor.close()

    @staticmethod
    def _ensure_sqlite_parent(url: str) -> None:
        parsed = make_url(url)
        if not parsed.drivername.startswith("sqlite") or not parsed.database:
            return
        if parsed.database == ":memory:":
            return
        Path(parsed.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    async def create_schema(self) -> None:
        # Importing registers ORM tables on Base.metadata.
        from god_news.infrastructure import repositories as _repositories  # noqa: F401
        from god_news.infrastructure import role_profiles as _role_profiles  # noqa: F401
        from god_news.infrastructure import source_runs as _source_runs  # noqa: F401
        from god_news.infrastructure import video_repository as _video_repository  # noqa: F401

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await self._apply_story_sqlite_additive_migrations(connection)
            await self._apply_sqlite_additive_migrations(connection)

    @staticmethod
    async def _apply_story_sqlite_additive_migrations(connection: AsyncConnection) -> None:
        """Keep the local SQLite development database forward-compatible.

        The project intentionally has no migration runner yet.  This narrow,
        idempotent migration only adds the nullable editorial-title column that
        existing installations need for the story PATCH contract.
        """

        if connection.dialect.name != "sqlite":
            return

        column_names = {
            column["name"]
            for column in await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_columns("stories")
            )
        }
        if "title" not in column_names:
            await connection.execute(text("ALTER TABLE stories ADD COLUMN title VARCHAR(500)"))

    @staticmethod
    async def _apply_sqlite_additive_migrations(connection: AsyncConnection) -> None:
        """Apply only backward-compatible SQLite schema additions.

        ``metadata.create_all`` intentionally does not alter an already-created
        table.  These nullable role fields therefore need an explicit additive
        migration for existing local installations.  The definitions are fixed
        constants, and the column check makes repeated application idempotent.
        """

        if connection.dialect.name != "sqlite":
            return

        result = await connection.exec_driver_sql("PRAGMA table_info(role_profiles)")
        existing_columns = {str(row[1]) for row in result.all()}
        additions = {
            "gpt_weights_path": "TEXT NULL",
            "sovits_weights_path": "TEXT NULL",
        }
        for column_name, definition in additions.items():
            if column_name not in existing_columns:
                await connection.exec_driver_sql(
                    f"ALTER TABLE role_profiles ADD COLUMN {column_name} {definition}"
                )

    async def healthcheck(self) -> None:
        async with self.sessions() as session:
            await session.execute(text("SELECT 1"))

    async def aclose(self) -> None:
        await self.engine.dispose()
