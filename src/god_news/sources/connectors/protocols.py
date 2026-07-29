from __future__ import annotations

from typing import Protocol

from god_news.sources.collectors.models import CollectorReadiness
from god_news.sources.connectors.models import SourceDiscoveryResult, SourceFetchRequest
from god_news.sources.models import SourceName


class SourceConnector(Protocol):
    """Replaceable discovery boundary for one externally governed source."""

    @property
    def source(self) -> SourceName: ...

    def readiness(self) -> CollectorReadiness: ...

    async def fetch(self, request: SourceFetchRequest) -> SourceDiscoveryResult: ...
