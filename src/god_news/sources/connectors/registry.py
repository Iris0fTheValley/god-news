from __future__ import annotations

from collections.abc import Iterable

from god_news.sources.collectors.models import CollectorReadiness
from god_news.sources.connectors.models import SourceDiscoveryResult, SourceFetchRequest
from god_news.sources.connectors.protocols import SourceConnector
from god_news.sources.models import SOURCE_ORDER, SourceName


class SourceConnectorRegistry:
    """Deterministic registry without source-specific branching."""

    def __init__(self, connectors: Iterable[SourceConnector]) -> None:
        self._connectors: dict[SourceName, SourceConnector] = {}
        for connector in connectors:
            if connector.source in self._connectors:
                raise ValueError(f"connector already registered for {connector.source!r}")
            self._connectors[connector.source] = connector

    @property
    def registered_sources(self) -> frozenset[SourceName]:
        return frozenset(self._connectors)

    def readiness(self) -> tuple[CollectorReadiness, ...]:
        return tuple(
            self._connectors[source].readiness()
            for source in SOURCE_ORDER
            if source in self._connectors
        )

    def connector(self, source: SourceName) -> SourceConnector:
        try:
            return self._connectors[source]
        except KeyError as exc:
            raise LookupError(f"no connector registered for {source!r}") from exc

    async def fetch(
        self,
        source: SourceName,
        request: SourceFetchRequest,
    ) -> SourceDiscoveryResult:
        return await self.connector(source).fetch(request)
