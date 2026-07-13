from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from god_news.sources.collectors.models import (
    CollectionErrorEvidence,
    CollectorReadiness,
    SourceCollectionRun,
)
from god_news.sources.collectors.rate_limited import (
    MAX_CONCURRENT_SOURCE_COLLECTIONS,
    MIN_SOURCE_COLLECTION_INTERVAL_SECONDS,
    RateLimitedSourceCollectorGateway,
)
from god_news.sources.models import SourceName


@dataclass(slots=True)
class ManualClock:
    now: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class RecordingCollectorGateway:
    def __init__(self, clock: ManualClock | None = None) -> None:
        self._clock = clock
        self.calls: list[tuple[SourceName, float | None]] = []

    def readiness(self) -> tuple[CollectorReadiness, ...]:
        sources: tuple[SourceName, ...] = ("dazhong", "reddit", "guardian", "pikabu")
        return tuple(
            CollectorReadiness(
                source=source,
                state="ready",
                enabled=True,
                configured=True,
                authorized=True,
            )
            for source in sources
        )

    async def collect(
        self,
        source: SourceName,
        *,
        limit: int | None = None,
    ) -> SourceCollectionRun:
        del limit
        self.calls.append((source, self._clock() if self._clock is not None else None))
        return _failed_collection(source)


class BlockingCollectorGateway(RecordingCollectorGateway):
    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.max_active = 0
        self.active_at_capacity = asyncio.Event()
        self.release = asyncio.Event()

    async def collect(
        self,
        source: SourceName,
        *,
        limit: int | None = None,
    ) -> SourceCollectionRun:
        del limit
        self.calls.append((source, None))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.active >= MAX_CONCURRENT_SOURCE_COLLECTIONS:
            self.active_at_capacity.set()
        try:
            await self.release.wait()
        finally:
            self.active -= 1
        return _failed_collection(source)


class BlockingSleeper:
    def __init__(self, clock: ManualClock) -> None:
        self._clock = clock
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.requested_seconds: float | None = None

    async def __call__(self, seconds: float) -> None:
        self.requested_seconds = seconds
        self.started.set()
        await self.release.wait()
        self._clock.now += seconds


def _failed_collection(source: SourceName) -> SourceCollectionRun:
    return SourceCollectionRun(
        source=source,
        outcome="failed",
        duration_ms=0,
        errors=[
            CollectionErrorEvidence(
                code="test_collector_result",
                message="A test collector intentionally returned no items.",
            )
        ],
    )


@pytest.mark.asyncio
async def test_per_source_cooldown_starts_after_previous_network_completion() -> None:
    clock = ManualClock()
    delegate = RecordingCollectorGateway(clock)
    gateway = RateLimitedSourceCollectorGateway(
        delegate,
        clock=clock,
        sleeper=clock.sleep,
    )

    first = await gateway.collect("guardian")
    clock.now += 9
    second = await gateway.collect("guardian")

    assert first.cooldown_wait_ms == 0
    assert second.cooldown_wait_ms == pytest.approx(21_000)
    assert clock.sleeps == [MIN_SOURCE_COLLECTION_INTERVAL_SECONDS - 9]
    assert delegate.calls == [("guardian", 0), ("guardian", 30)]


@pytest.mark.asyncio
async def test_global_network_collection_cap_is_enforced() -> None:
    delegate = BlockingCollectorGateway()
    gateway = RateLimitedSourceCollectorGateway(delegate)
    tasks = [
        asyncio.create_task(gateway.collect(source))
        for source in ("dazhong", "reddit", "guardian", "pikabu")
    ]

    await asyncio.wait_for(delegate.active_at_capacity.wait(), timeout=1)
    assert delegate.active == MAX_CONCURRENT_SOURCE_COLLECTIONS
    assert delegate.max_active == MAX_CONCURRENT_SOURCE_COLLECTIONS
    assert len(delegate.calls) == MAX_CONCURRENT_SOURCE_COLLECTIONS

    delegate.release.set()
    await asyncio.gather(*tasks)
    assert delegate.max_active == MAX_CONCURRENT_SOURCE_COLLECTIONS


@pytest.mark.asyncio
async def test_cooling_wait_does_not_consume_a_network_collection_slot() -> None:
    clock = ManualClock()
    delegate = BlockingCollectorGateway()
    sleeper = BlockingSleeper(clock)
    gateway = RateLimitedSourceCollectorGateway(
        delegate,
        clock=clock,
        sleeper=sleeper,
    )

    delegate.release.set()
    await gateway.collect("guardian")
    delegate.release = asyncio.Event()

    cooling = asyncio.create_task(gateway.collect("guardian"))
    await asyncio.wait_for(sleeper.started.wait(), timeout=1)
    assert sleeper.requested_seconds == MIN_SOURCE_COLLECTION_INTERVAL_SECONDS

    other_tasks = [
        asyncio.create_task(gateway.collect(source)) for source in ("reddit", "pikabu")
    ]
    await asyncio.wait_for(delegate.active_at_capacity.wait(), timeout=1)
    assert delegate.active == MAX_CONCURRENT_SOURCE_COLLECTIONS

    delegate.release.set()
    await asyncio.gather(*other_tasks)
    sleeper.release.set()
    await cooling


@pytest.mark.asyncio
async def test_cooling_wait_is_cancellable_before_the_network_collector_runs() -> None:
    clock = ManualClock()
    delegate = RecordingCollectorGateway(clock)
    sleeper = BlockingSleeper(clock)
    gateway = RateLimitedSourceCollectorGateway(
        delegate,
        clock=clock,
        sleeper=sleeper,
    )

    await gateway.collect("guardian")
    cooling = asyncio.create_task(gateway.collect("guardian"))
    await asyncio.wait_for(sleeper.started.wait(), timeout=1)
    cooling.cancel()

    with pytest.raises(asyncio.CancelledError):
        await cooling
    assert [source for source, _ in delegate.calls] == ["guardian"]
