from __future__ import annotations

import asyncio
import copy
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from god_news.infrastructure.database import Base
from god_news.sources.schedule_errors import SourceScheduleConflictError
from god_news.sources.schedule_models import SourceScheduleState


class SourceScheduleRow(Base):
    __tablename__ = "source_schedules"

    schedule_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


def _payload(state: SourceScheduleState) -> str:
    return state.model_dump_json()


def _to_state(row: SourceScheduleRow) -> SourceScheduleState:
    state = SourceScheduleState.model_validate_json(row.payload_json)
    if state.version != row.version or state.enabled != row.enabled:
        raise ValueError("source schedule payload does not match its row")
    return state


class SqlAlchemySourceScheduleRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_or_create(self, initial: SourceScheduleState) -> SourceScheduleState:
        async with self._sessions() as session, session.begin():
            row = await session.get(SourceScheduleRow, initial.schedule_id)
            if row is None:
                row = SourceScheduleRow(
                    schedule_id=initial.schedule_id,
                    enabled=initial.enabled,
                    version=initial.version,
                    updated_at=initial.updated_at,
                    payload_json=_payload(initial),
                )
                session.add(row)
                return initial
            return _to_state(row)

    async def save(
        self,
        state: SourceScheduleState,
        *,
        expected_version: int,
    ) -> SourceScheduleState:
        saved = state.model_copy(update={"version": expected_version + 1})
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(SourceScheduleRow)
                .where(
                    SourceScheduleRow.schedule_id == state.schedule_id,
                    SourceScheduleRow.version == expected_version,
                )
                .values(
                    enabled=saved.enabled,
                    version=saved.version,
                    updated_at=saved.updated_at,
                    payload_json=_payload(saved),
                )
            )
            rowcount = result.rowcount if isinstance(result, CursorResult) else 0
        if rowcount != 1:
            raise SourceScheduleConflictError()
        return saved


class InMemorySourceScheduleRepository:
    def __init__(self) -> None:
        self._states: dict[str, SourceScheduleState] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, initial: SourceScheduleState) -> SourceScheduleState:
        async with self._lock:
            state = self._states.setdefault(initial.schedule_id, copy.deepcopy(initial))
            return copy.deepcopy(state)

    async def save(
        self,
        state: SourceScheduleState,
        *,
        expected_version: int,
    ) -> SourceScheduleState:
        async with self._lock:
            current = self._states.get(state.schedule_id)
            if current is None or current.version != expected_version:
                raise SourceScheduleConflictError()
            saved = state.model_copy(update={"version": expected_version + 1})
            self._states[state.schedule_id] = copy.deepcopy(saved)
            return copy.deepcopy(saved)
