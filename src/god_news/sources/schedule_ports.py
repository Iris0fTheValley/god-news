from __future__ import annotations

from typing import Protocol

from god_news.sources.schedule_models import SourceScheduleState


class SourceScheduleRepository(Protocol):
    async def get_or_create(self, initial: SourceScheduleState) -> SourceScheduleState: ...

    async def save(
        self,
        state: SourceScheduleState,
        *,
        expected_version: int,
    ) -> SourceScheduleState: ...
