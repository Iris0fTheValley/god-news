from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from god_news.api.app import create_app
from god_news.application.source_schedule import SourceCollectionScheduler
from god_news.infrastructure.database import Database
from god_news.infrastructure.source_schedule import (
    InMemorySourceScheduleRepository,
    SqlAlchemySourceScheduleRepository,
)
from god_news.sources.collectors.models import CollectorReadiness
from god_news.sources.run_models import SourceRun

from .conftest import Stack


def readiness(source: str, state: str = "ready") -> CollectorReadiness:
    return CollectorReadiness(
        source=source,
        state=state,
        enabled=state != "disabled",
        configured=state not in {"disabled", "unconfigured"},
        authorized=state == "ready",
    )


class RecordingSourceRuns:
    def __init__(self) -> None:
        self.started: list[SourceRun] = []
        self.active: list[SourceRun] = []

    def readiness(self):  # type: ignore[no-untyped-def]
        return (
            readiness("guardian"),
            readiness("reddit", "unconfigured"),
            readiness("dazhong", "unauthorized"),
            readiness("pikabu", "disabled"),
        )

    async def active_runs(self):  # type: ignore[no-untyped-def]
        return self.active

    async def start_if_source_idle(self, request, *, trace_id):  # type: ignore[no-untyped-def]
        if any(run.request.source == request.source for run in self.active):
            return None
        run = SourceRun(trace_id=trace_id, request=request)
        self.started.append(run)
        self.active.append(run)
        return run


def make_scheduler(
    source_runs: RecordingSourceRuns,
    repository: InMemorySourceScheduleRepository | None = None,
) -> SourceCollectionScheduler:
    return SourceCollectionScheduler(
        repository=repository or InMemorySourceScheduleRepository(),
        source_runs=source_runs,  # type: ignore[arg-type]
        interval_seconds=30,
        poll_interval_seconds=60,
        collection_limits={"guardian": 5, "reddit": 5, "dazhong": 5, "pikabu": 5},
    )


@pytest.mark.asyncio
async def test_source_schedule_defaults_off_and_starts_only_ready_idle_sources() -> None:
    source_runs = RecordingSourceRuns()
    scheduler = make_scheduler(source_runs)
    try:
        disabled = await scheduler.snapshot()
        assert disabled.enabled is False
        assert disabled.next_run_at is None
        assert await scheduler.run_due(now=datetime.now(UTC) + timedelta(days=1)) == []

        enabled = await scheduler.enable()
        assert enabled.enabled is True
        assert enabled.next_run_at is not None
        assert [run.request.source for run in source_runs.started] == ["guardian"]
        assert source_runs.started[0].request.requested_by == "schedule:source-auto-collection"

        # The next due cycle sees the still-active Guardian run and does not overlap it.
        state = await scheduler.snapshot()
        assert state.next_run_at is not None
        assert await scheduler.run_due(now=state.next_run_at) == []

        stopped = await scheduler.disable()
        assert stopped.enabled is False
        assert stopped.next_run_at is None
        assert len(stopped.active_runs) == 1
    finally:
        await scheduler.aclose()


@pytest.mark.asyncio
async def test_source_schedule_operator_intent_survives_repository_restart(tmp_path) -> None:
    database = Database(f"sqlite+aiosqlite:///{(tmp_path / 'schedule.db').as_posix()}")
    await database.create_schema()
    try:
        first = SourceCollectionScheduler(
            repository=SqlAlchemySourceScheduleRepository(database.sessions),
            source_runs=RecordingSourceRuns(),  # type: ignore[arg-type]
            interval_seconds=30,
            poll_interval_seconds=60,
            collection_limits={
                "guardian": 1,
                "reddit": 1,
                "dazhong": 1,
                "pikabu": 1,
            },
        )
        enabled = await first.enable()
        assert enabled.enabled is True
        await first.aclose()

        second = SourceCollectionScheduler(
            repository=SqlAlchemySourceScheduleRepository(database.sessions),
            source_runs=RecordingSourceRuns(),  # type: ignore[arg-type]
            interval_seconds=30,
            poll_interval_seconds=60,
            collection_limits={
                "guardian": 1,
                "reddit": 1,
                "dazhong": 1,
                "pikabu": 1,
            },
        )
        persisted = await second.snapshot()
        assert persisted.enabled is True
        await second.disable()
        await second.aclose()
    finally:
        await database.aclose()


@pytest.mark.asyncio
async def test_source_schedule_api_controls_persisted_scheduler(stack: Stack) -> None:
    scheduler = make_scheduler(RecordingSourceRuns())
    stack.container.source_scheduler = scheduler

    async def factory(settings):  # type: ignore[no-untyped-def]
        del settings
        return stack.container

    app = create_app(stack.settings, container_factory=factory)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            initial = await client.get("/api/v1/source-schedule")
            assert initial.status_code == 200
            assert initial.json()["enabled"] is False
            assert "interval_seconds" not in initial.json()

            started = await client.post("/api/v1/source-schedule/start")
            assert started.status_code == 200
            assert started.json()["enabled"] is True

            stopped = await client.post("/api/v1/source-schedule/stop")
            assert stopped.status_code == 200
            assert stopped.json()["enabled"] is False
            assert stopped.json()["next_run_at"] is None
