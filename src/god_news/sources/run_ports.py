from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from god_news.domain.models import SourceItemIngestRequest, Story
from god_news.sources.collectors.models import CollectorReadiness, SourceCollectionRun
from god_news.sources.models import SourceName
from god_news.sources.run_models import SourceRun, SourceRunStatus


class SourceCollectorGateway(Protocol):
    def readiness(self) -> tuple[CollectorReadiness, ...]: ...

    async def collect(
        self,
        source: SourceName,
        *,
        limit: int | None = None,
    ) -> SourceCollectionRun: ...


class SourceStoryIngestor(Protocol):
    async def ingest_source_item(
        self,
        request: SourceItemIngestRequest,
        *,
        trace_id: UUID | None = None,
    ) -> Story: ...


class SourceRunRepository(Protocol):
    async def create(self, run: SourceRun) -> SourceRun: ...

    async def get(self, run_id: UUID) -> SourceRun: ...

    async def list(
        self,
        *,
        source: SourceName | None = None,
        status: SourceRunStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[SourceRun]: ...

    async def save(self, run: SourceRun, *, expected_version: int) -> SourceRun: ...

    async def recover_interrupted(self) -> int: ...
