from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import ValidationError

from god_news.api.app import create_app
from god_news.application.source_runs import SourceRunService
from god_news.domain.enums import SpeechEmotion, StoryStatus
from god_news.infrastructure.database import Database
from god_news.infrastructure.source_runs import (
    InMemorySourceRunRepository,
    SqlAlchemySourceRunRepository,
)
from god_news.sources.collectors.models import (
    CollectionAttempt,
    CollectorReadiness,
    SourceCollectionRun,
)
from god_news.sources.collectors.rate_limited import RateLimitedSourceCollectorGateway
from god_news.sources.models import RawGuardianItem, SourceName
from god_news.sources.run_models import SourceRun, SourceRunRequest, SourceRunStatus

from .conftest import Stack

GUARDIAN_FIXTURE = RawGuardianItem.model_validate_json(
    (Path(__file__).parent / "fixtures" / "sources" / "guardian.json").read_text(
        encoding="utf-8"
    )
)


def test_source_run_emotion_uses_the_seven_voice_labels() -> None:
    legacy = SourceRunRequest(source="guardian", requested_by="scheduler", emotion="neutral")
    assert legacy.emotion is SpeechEmotion.HAPPINESS
    with pytest.raises(ValidationError):
        SourceRunRequest(source="guardian", requested_by="scheduler", emotion="calm")


class StaticCollectorGateway:
    def __init__(self, run: SourceCollectionRun) -> None:
        self.run = run

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
        assert source == self.run.source
        assert limit is not None
        return self.run


class BlockingCollectorGateway(StaticCollectorGateway):
    def __init__(self, run: SourceCollectionRun) -> None:
        super().__init__(run)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def collect(
        self,
        source: SourceName,
        *,
        limit: int | None = None,
    ) -> SourceCollectionRun:
        self.started.set()
        await self.release.wait()
        return await super().collect(source, limit=limit)


class ManualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.asyncio
async def test_source_run_persists_progress_and_deduplicates_items(stack: Stack) -> None:
    collection = SourceCollectionRun(
        source="guardian",
        outcome="succeeded",
        duration_ms=2,
        items=[GUARDIAN_FIXTURE, GUARDIAN_FIXTURE],
        attempts=[
            CollectionAttempt(
                sequence=0,
                layer="guardian-content-api",
                operation="listing",
                outcome="succeeded",
                duration_ms=1,
                item_count=2,
            )
        ],
    )
    repository = InMemorySourceRunRepository()
    service = SourceRunService(
        repository=repository,
        collectors=StaticCollectorGateway(collection),
        normalizer=stack.container.source_normalizers,
        ingestor=stack.workflow,
    )
    trace_id = uuid4()
    started = await service.start(
        SourceRunRequest(source="guardian", limit=2, requested_by="test-editor"),
        trace_id=trace_id,
    )
    completed = await service.wait(started.run_id)

    assert started.status is SourceRunStatus.QUEUED
    assert completed.status is SourceRunStatus.COMPLETED
    assert completed.trace_id == trace_id
    assert completed.items_discovered == 2
    assert completed.ingested_count == 1
    assert completed.duplicate_count == 1
    assert completed.failed_count == 0
    assert completed.failure_rate == 0
    assert completed.version >= 5
    stories = await stack.workflow.list(status=StoryStatus.PENDING_FIRST_REVIEW, limit=10, offset=0)
    assert len(stories) == 1
    await service.aclose()


@pytest.mark.asyncio
async def test_source_run_persists_rate_limit_wait(stack: Stack) -> None:
    collection = SourceCollectionRun(
        source="guardian",
        outcome="succeeded",
        duration_ms=1,
        items=[GUARDIAN_FIXTURE],
    )
    clock = ManualClock()
    service = SourceRunService(
        repository=InMemorySourceRunRepository(),
        collectors=RateLimitedSourceCollectorGateway(
            StaticCollectorGateway(collection),
            clock=clock,
            sleeper=clock.sleep,
        ),
        normalizer=stack.container.source_normalizers,
        ingestor=stack.workflow,
    )

    first = await service.start(
        SourceRunRequest(source="guardian", requested_by="test-editor"),
        trace_id=uuid4(),
    )
    first_completed = await service.wait(first.run_id)
    clock.now += 7
    second = await service.start(
        SourceRunRequest(source="guardian", requested_by="test-editor"),
        trace_id=uuid4(),
    )
    second_completed = await service.wait(second.run_id)

    assert first_completed.cooldown_wait_ms == 0
    assert second_completed.cooldown_wait_ms == pytest.approx(23_000)
    await service.aclose()


@pytest.mark.asyncio
async def test_sql_source_runs_recover_interrupted_work(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'runs.db').as_posix()}")
    await database.create_schema()
    repository = SqlAlchemySourceRunRepository(database.sessions)
    queued = SourceRun(request=SourceRunRequest(source="reddit", requested_by="scheduler"))
    try:
        await repository.create(queued)
        assert await repository.recover_interrupted() == 1
        recovered = await repository.get(queued.run_id)
        assert recovered.status is SourceRunStatus.FAILED
        assert recovered.run_error is not None
        assert recovered.run_error.code == "interrupted_by_restart"
        assert recovered.version == 2
        assert await repository.recover_interrupted() == 0
    finally:
        await database.aclose()


@pytest.mark.asyncio
async def test_sql_source_run_persists_cooldown_wait_telemetry(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'runs.db').as_posix()}")
    await database.create_schema()
    repository = SqlAlchemySourceRunRepository(database.sessions)
    run = SourceRun(
        request=SourceRunRequest(source="reddit", requested_by="scheduler"),
        cooldown_wait_ms=30_000,
    )
    try:
        await repository.create(run)
        reloaded = await repository.get(run.run_id)
        assert reloaded.cooldown_wait_ms == 30_000
    finally:
        await database.aclose()


@pytest.mark.asyncio
async def test_source_run_api_starts_and_reports_background_progress(stack: Stack) -> None:
    collection = SourceCollectionRun(
        source="guardian",
        outcome="succeeded",
        duration_ms=1,
        items=[GUARDIAN_FIXTURE],
    )
    service = SourceRunService(
        repository=InMemorySourceRunRepository(),
        collectors=StaticCollectorGateway(collection),
        normalizer=stack.container.source_normalizers,
        ingestor=stack.workflow,
    )
    stack.container.source_runs = service

    async def factory(settings):  # type: ignore[no-untyped-def]
        del settings
        return stack.container

    app = create_app(stack.settings, container_factory=factory)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/source-runs",
                json={
                    "source": "guardian",
                    "limit": 1,
                    "requested_by": "api-editor",
                },
            )
            assert response.status_code == 202
            run_id = response.json()["run_id"]
            await service.wait(UUID(run_id))

            fetched = await client.get(f"/api/v1/source-runs/{run_id}")
            assert fetched.status_code == 200
            assert fetched.json()["status"] == "completed"
            assert fetched.json()["ingested_count"] == 1

            listed = await client.get(
                "/api/v1/source-runs",
                params={"source": "guardian", "run_status": "completed"},
            )
            assert [item["run_id"] for item in listed.json()] == [run_id]

            readiness = await client.get("/api/v1/sources/collectors")
            assert readiness.status_code == 200
            assert len(readiness.json()["collectors"]) == 4


@pytest.mark.asyncio
async def test_source_run_can_be_cancelled_without_losing_terminal_evidence(stack: Stack) -> None:
    collection = SourceCollectionRun(
        source="guardian",
        outcome="succeeded",
        duration_ms=1,
        items=[GUARDIAN_FIXTURE],
    )
    collectors = BlockingCollectorGateway(collection)
    service = SourceRunService(
        repository=InMemorySourceRunRepository(),
        collectors=collectors,
        normalizer=stack.container.source_normalizers,
        ingestor=stack.workflow,
    )
    started = await service.start(
        SourceRunRequest(source="guardian", requested_by="test-editor"),
        trace_id=uuid4(),
    )
    await collectors.started.wait()
    cancelled = await service.cancel(started.run_id)
    assert cancelled.status is SourceRunStatus.CANCELLED
    assert cancelled.run_error is not None
    assert cancelled.run_error.code == "operator_cancelled"
    await service.aclose()


@pytest.mark.asyncio
async def test_shutdown_cancellation_is_distinct_from_operator_cancellation(stack: Stack) -> None:
    collection = SourceCollectionRun(
        source="guardian",
        outcome="succeeded",
        duration_ms=1,
        items=[GUARDIAN_FIXTURE],
    )
    collectors = BlockingCollectorGateway(collection)
    repository = InMemorySourceRunRepository()
    service = SourceRunService(
        repository=repository,
        collectors=collectors,
        normalizer=stack.container.source_normalizers,
        ingestor=stack.workflow,
    )
    started = await service.start(
        SourceRunRequest(source="guardian", requested_by="test-editor"),
        trace_id=uuid4(),
    )
    await collectors.started.wait()
    await service.aclose()

    cancelled = await repository.get(started.run_id)
    assert cancelled.status is SourceRunStatus.CANCELLED
    assert cancelled.run_error is not None
    assert cancelled.run_error.code == "service_shutdown"
