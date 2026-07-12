from __future__ import annotations

from typing import Protocol

from god_news.sources.collectors.models import CollectorReadiness, SourceCollectionRun
from god_news.sources.models import SourceName


class SourceCollector(Protocol):
    """Replaceable, application-facing boundary for a fixed source collector."""

    @property
    def source(self) -> SourceName: ...

    def readiness(self) -> CollectorReadiness: ...

    async def collect(self, *, limit: int | None = None) -> SourceCollectionRun: ...
