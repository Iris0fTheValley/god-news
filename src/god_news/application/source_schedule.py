from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from god_news.application.source_runs import SourceRunService
from god_news.sources.models import SourceName
from god_news.sources.run_errors import SourceRunCapacityError
from god_news.sources.run_models import SourceRunRequest
from god_news.sources.schedule_models import (
    ActiveScheduledSourceRun,
    SourceScheduleSnapshot,
    SourceScheduleState,
)
from god_news.sources.schedule_ports import SourceScheduleRepository

logger = logging.getLogger(__name__)


class SourceCollectionScheduler:
    """Persistent control plane for automatic source collection.

    It decides only *when* a ready source should get a normal SourceRun. The
    SourceRunService remains the sole owner of collection and ingestion.
    """

    def __init__(
        self,
        *,
        repository: SourceScheduleRepository,
        source_runs: SourceRunService,
        interval_seconds: float,
        poll_interval_seconds: float,
        collection_limits: Mapping[SourceName, int],
        initially_enabled: bool = False,
    ) -> None:
        if interval_seconds < 30:
            raise ValueError("automatic source cadence must be at least 30 seconds")
        if poll_interval_seconds <= 0:
            raise ValueError("source schedule polling interval must be positive")
        self._repository = repository
        self._source_runs = source_runs
        self._interval_seconds = interval_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._collection_limits = dict(collection_limits)
        self._initially_enabled = initially_enabled
        self._control_lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._closing = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        async with self._control_lock:
            state = await self._load()
            if state.enabled:
                self._ensure_loop_locked()

    async def snapshot(self) -> SourceScheduleSnapshot:
        state = await self._load()
        readiness = self._source_runs.readiness()
        active = await self._source_runs.active_runs()
        return SourceScheduleSnapshot(
            schedule_id=state.schedule_id,
            enabled=state.enabled,
            next_run_at=state.next_run_at,
            last_tick_at=state.last_tick_at,
            last_started_run_ids=state.last_started_run_ids,
            ready_sources=[item.source for item in readiness if item.state == "ready"],
            active_runs=[
                ActiveScheduledSourceRun(
                    source=run.request.source,
                    run_id=run.run_id,
                    status=run.status,
                )
                for run in active
            ],
            version=state.version,
            updated_at=state.updated_at,
        )

    async def enable(self) -> SourceScheduleSnapshot:
        async with self._control_lock:
            state = await self._load()
            if not state.enabled:
                now = datetime.now(UTC)
                state = await self._repository.save(
                    state.model_copy(
                        update={"enabled": True, "next_run_at": now, "updated_at": now}
                    ),
                    expected_version=state.version,
                )
        try:
            # Starting automation has immediate, observable meaning. The run
            # records themselves remain asynchronous and independently cancellable.
            await self.run_due()
        finally:
            async with self._control_lock:
                self._ensure_loop_locked()
            self._wake.set()
        return await self.snapshot()

    async def disable(self) -> SourceScheduleSnapshot:
        async with self._control_lock:
            state = await self._load()
            if state.enabled:
                now = datetime.now(UTC)
                state = await self._repository.save(
                    state.model_copy(
                        update={"enabled": False, "next_run_at": None, "updated_at": now}
                    ),
                    expected_version=state.version,
                )
            self._wake.set()
        return await self.snapshot()

    async def run_due(self, *, now: datetime | None = None) -> list[str]:
        candidate = now or datetime.now(UTC)
        if candidate.tzinfo is None:
            raise ValueError("source schedule timestamps must be timezone-aware")
        resolved_now = candidate.astimezone(UTC)
        async with self._control_lock:
            state = await self._load()
            if (
                not state.enabled
                or state.next_run_at is None
                or state.next_run_at > resolved_now
            ):
                return []
            state = await self._repository.save(
                state.model_copy(
                    update={
                        "next_run_at": resolved_now
                        + timedelta(seconds=self._interval_seconds),
                        "last_tick_at": resolved_now,
                        "updated_at": resolved_now,
                    }
                ),
                expected_version=state.version,
            )

            started: dict[SourceName, UUID] = {}
            for readiness in self._source_runs.readiness():
                if readiness.state != "ready":
                    continue
                limit = self._collection_limits.get(readiness.source)
                if limit is None:
                    logger.error("missing automatic collection limit source=%s", readiness.source)
                    continue
                try:
                    run = await self._source_runs.start_if_source_idle(
                        SourceRunRequest(
                            source=readiness.source,
                            limit=limit,
                            requested_by=f"schedule:{state.schedule_id}",
                        ),
                        trace_id=uuid4(),
                    )
                except SourceRunCapacityError:
                    logger.info("automatic collection capacity reached source=%s", readiness.source)
                    break
                if run is not None:
                    started[readiness.source] = run.run_id

            if started:
                state = await self._repository.save(
                    state.model_copy(
                        update={
                            "last_started_run_ids": {
                                **state.last_started_run_ids,
                                **started,
                            },
                            "updated_at": datetime.now(UTC),
                        }
                    ),
                    expected_version=state.version,
                )
            return [str(run_id) for run_id in started.values()]

    async def aclose(self) -> None:
        async with self._control_lock:
            self._closing = True
            self._wake.set()
            task, self._task = self._task, None
        if task is not None:
            await task

    async def _load(self) -> SourceScheduleState:
        now = datetime.now(UTC)
        initial = SourceScheduleState(
            enabled=self._initially_enabled,
            next_run_at=now if self._initially_enabled else None,
            updated_at=now,
        )
        return await self._repository.get_or_create(initial)

    def _ensure_loop_locked(self) -> None:
        if self._closing:
            return
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._run_loop(),
                name="god-news-source-collection-scheduler",
            )

    async def _run_loop(self) -> None:
        logger.info("source collection scheduler loop started")
        try:
            while not self._closing:
                # Clear before observing state so a concurrent stop/close after
                # this point cannot be lost between a tick and the wait below.
                self._wake.clear()
                state = await self._load()
                if not state.enabled:
                    break
                try:
                    await self.run_due()
                except Exception:
                    logger.exception("source collection scheduler tick failed")
                if self._closing:
                    break
                state = await self._load()
                if not state.enabled:
                    break
                try:
                    await asyncio.wait_for(
                        self._wake.wait(),
                        timeout=self._poll_interval_seconds,
                    )
                except TimeoutError:
                    pass
        finally:
            logger.info("source collection scheduler loop stopped")
