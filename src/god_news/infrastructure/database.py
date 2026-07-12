from __future__ import annotations

from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
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

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def healthcheck(self) -> None:
        async with self.sessions() as session:
            await session.execute(text("SELECT 1"))

    async def aclose(self) -> None:
        await self.engine.dispose()
