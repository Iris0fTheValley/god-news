from __future__ import annotations

import asyncio
import copy
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, Text, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from god_news.infrastructure.database import Base
from god_news.sources.collectors.models import CollectionErrorEvidence
from god_news.sources.models import SourceName
from god_news.sources.run_errors import SourceRunConflictError, SourceRunNotFoundError
from god_news.sources.run_models import SourceRun, SourceRunStatus


class SourceRunRow(Base):
    __tablename__ = "source_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


def _payload(run: SourceRun) -> str:
    return run.model_dump_json(exclude_computed_fields=True)


def _to_run(row: SourceRunRow) -> SourceRun:
    run = SourceRun.model_validate_json(row.payload_json)
    if run.version != row.version:
        raise ValueError("source run payload version does not match its row")
    return run


class SqlAlchemySourceRunRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, run: SourceRun) -> SourceRun:
        row = SourceRunRow(
            run_id=str(run.run_id),
            source=run.request.source,
            status=run.status.value,
            version=run.version,
            created_at=run.created_at,
            updated_at=run.updated_at,
            payload_json=_payload(run),
        )
        try:
            async with self._sessions() as session, session.begin():
                session.add(row)
        except IntegrityError as exc:
            raise SourceRunConflictError() from exc
        return run

    async def get(self, run_id: UUID) -> SourceRun:
        async with self._sessions() as session:
            row = await session.get(SourceRunRow, str(run_id))
        if row is None:
            raise SourceRunNotFoundError(run_id)
        return _to_run(row)

    async def list(
        self,
        *,
        source: SourceName | None = None,
        status: SourceRunStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[SourceRun]:
        statement = select(SourceRunRow)
        if source is not None:
            statement = statement.where(SourceRunRow.source == source)
        if status is not None:
            statement = statement.where(SourceRunRow.status == status.value)
        statement = statement.order_by(SourceRunRow.created_at.desc()).limit(limit).offset(offset)
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
        return [_to_run(row) for row in rows]

    async def save(self, run: SourceRun, *, expected_version: int) -> SourceRun:
        saved = run.model_copy(update={"version": expected_version + 1})
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(SourceRunRow)
                .where(
                    SourceRunRow.run_id == str(run.run_id),
                    SourceRunRow.version == expected_version,
                )
                .values(
                    source=saved.request.source,
                    status=saved.status.value,
                    version=saved.version,
                    updated_at=saved.updated_at,
                    payload_json=_payload(saved),
                )
            )
            rowcount = result.rowcount if isinstance(result, CursorResult) else 0
        if rowcount != 1:
            await self._raise_missing_or_conflict(run.run_id)
        return saved

    async def recover_interrupted(self) -> int:
        active = (
            SourceRunStatus.QUEUED.value,
            SourceRunStatus.COLLECTING.value,
            SourceRunStatus.INGESTING.value,
        )
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(SourceRunRow).where(SourceRunRow.status.in_(active))
                )
            ).all()
        recovered = 0
        for row in rows:
            run = _to_run(row)
            now = datetime.now(UTC)
            failed = run.model_copy(
                update={
                    "status": SourceRunStatus.FAILED,
                    "current_item_index": None,
                    "current_external_id": None,
                    "current_title": None,
                    "current_url": None,
                    "started_at": run.started_at or now,
                    "finished_at": now,
                    "updated_at": now,
                    "run_error": CollectionErrorEvidence(
                        code="interrupted_by_restart",
                        message="The service restarted before this source run finished.",
                        retryable=True,
                    ),
                }
            )
            try:
                await self.save(failed, expected_version=run.version)
            except (SourceRunConflictError, SourceRunNotFoundError):
                continue
            recovered += 1
        return recovered

    async def _raise_missing_or_conflict(self, run_id: UUID) -> None:
        async with self._sessions() as session:
            exists = await session.scalar(
                select(SourceRunRow.run_id).where(SourceRunRow.run_id == str(run_id)).limit(1)
            )
        if exists is None:
            raise SourceRunNotFoundError(run_id)
        raise SourceRunConflictError()


class InMemorySourceRunRepository:
    def __init__(self) -> None:
        self._runs: dict[UUID, SourceRun] = {}
        self._lock = asyncio.Lock()

    async def create(self, run: SourceRun) -> SourceRun:
        async with self._lock:
            if run.run_id in self._runs:
                raise SourceRunConflictError()
            self._runs[run.run_id] = copy.deepcopy(run)
        return copy.deepcopy(run)

    async def get(self, run_id: UUID) -> SourceRun:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise SourceRunNotFoundError(run_id)
            return copy.deepcopy(run)

    async def list(
        self,
        *,
        source: SourceName | None = None,
        status: SourceRunStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[SourceRun]:
        async with self._lock:
            runs = sorted(self._runs.values(), key=lambda item: item.created_at, reverse=True)
            if source is not None:
                runs = [run for run in runs if run.request.source == source]
            if status is not None:
                runs = [run for run in runs if run.status is status]
            return copy.deepcopy(runs[offset : offset + limit])

    async def save(self, run: SourceRun, *, expected_version: int) -> SourceRun:
        async with self._lock:
            current = self._runs.get(run.run_id)
            if current is None:
                raise SourceRunNotFoundError(run.run_id)
            if current.version != expected_version:
                raise SourceRunConflictError()
            saved = run.model_copy(update={"version": expected_version + 1})
            self._runs[run.run_id] = copy.deepcopy(saved)
            return copy.deepcopy(saved)

    async def recover_interrupted(self) -> int:
        async with self._lock:
            active = {
                SourceRunStatus.QUEUED,
                SourceRunStatus.COLLECTING,
                SourceRunStatus.INGESTING,
            }
            recovered = 0
            for run_id, run in tuple(self._runs.items()):
                if run.status not in active:
                    continue
                now = datetime.now(UTC)
                self._runs[run_id] = run.model_copy(
                    update={
                        "status": SourceRunStatus.FAILED,
                        "current_item_index": None,
                        "current_external_id": None,
                        "current_title": None,
                        "current_url": None,
                        "started_at": run.started_at or now,
                        "finished_at": now,
                        "updated_at": now,
                        "version": run.version + 1,
                        "run_error": CollectionErrorEvidence(
                            code="interrupted_by_restart",
                            message="The service restarted before this source run finished.",
                            retryable=True,
                        ),
                    }
                )
                recovered += 1
            return recovered
