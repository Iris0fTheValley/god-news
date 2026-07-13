from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic

from god_news.sources.collectors.models import CollectorReadiness, SourceCollectionRun
from god_news.sources.models import SourceName
from god_news.sources.run_ports import SourceCollectorGateway

# These are deliberate backend safety policies, not operator-facing knobs.
# A deployment that needs a different policy must change and review code rather
# than exposing a control that can accidentally overload a source.
MIN_SOURCE_COLLECTION_INTERVAL_SECONDS = 30.0
MAX_CONCURRENT_SOURCE_COLLECTIONS = 2

_SOURCES: tuple[SourceName, ...] = ("dazhong", "reddit", "guardian", "pikabu")
_Clock = Callable[[], float]
_Sleeper = Callable[[float], Awaitable[None]]


class RateLimitedSourceCollectorGateway:
    """Enforce collection cadence around any source collector gateway.

    The per-source lock is intentionally scoped to network collection only.
    Source ingestion, translation, and review-pipeline work remain outside this
    decorator so a slow LLM cannot reserve a scarce collection slot.
    """

    def __init__(
        self,
        delegate: SourceCollectorGateway,
        *,
        clock: _Clock = monotonic,
        sleeper: _Sleeper = asyncio.sleep,
    ) -> None:
        self._delegate = delegate
        self._clock = clock
        self._sleeper = sleeper
        self._source_locks: dict[SourceName, asyncio.Lock] = {
            source: asyncio.Lock() for source in _SOURCES
        }
        self._collection_slots = asyncio.Semaphore(MAX_CONCURRENT_SOURCE_COLLECTIONS)
        self._last_network_completion: dict[SourceName, float] = {}

    def readiness(self) -> tuple[CollectorReadiness, ...]:
        return self._delegate.readiness()

    async def collect(
        self,
        source: SourceName,
        *,
        limit: int | None = None,
    ) -> SourceCollectionRun:
        """Collect after a cancellable per-source cooldown.

        The cooldown is measured from the previous collection completion to
        the next call into the wrapped network collector. Waiting happens
        before acquiring the global semaphore, so it never consumes an active
        network-collection slot.
        """

        async with self._source_locks[source]:
            cooldown_wait_seconds = await self._wait_for_source_cooldown(source)
            network_started = False
            try:
                async with self._collection_slots:
                    network_started = True
                    collected = await self._delegate.collect(source, limit=limit)
            finally:
                if network_started:
                    self._last_network_completion[source] = self._clock()

            return collected.model_copy(
                update={"cooldown_wait_ms": cooldown_wait_seconds * 1_000}
            )

    async def _wait_for_source_cooldown(self, source: SourceName) -> float:
        waited_seconds = 0.0
        while True:
            completed_at = self._last_network_completion.get(source)
            if completed_at is None:
                return waited_seconds
            remaining = MIN_SOURCE_COLLECTION_INTERVAL_SECONDS - (self._clock() - completed_at)
            if remaining <= 0:
                return waited_seconds
            started_waiting_at = self._clock()
            await self._sleeper(remaining)
            waited_seconds += max(0.0, self._clock() - started_waiting_at)
