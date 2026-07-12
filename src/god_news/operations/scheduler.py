from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from god_news.logging import reset_trace_id, set_trace_id, trace_id_var
from god_news.operations.errors import OperationUnavailableError
from god_news.operations.models import (
    OperationCommand,
    OperationKind,
    OperationRun,
    OperationRunStatus,
    RetentionCleanupCommand,
    ScheduleSnapshot,
    TriggerOrigin,
    utc_now,
)
from god_news.operations.ports import OperationHandler

logger = logging.getLogger(__name__)


class OperationDispatcher:
    """One typed execution boundary shared by manual and scheduled triggers."""

    def __init__(self, handlers: Sequence[OperationHandler], *, history_limit: int = 100) -> None:
        if history_limit < 1:
            raise ValueError("history_limit must be positive")
        self._handlers: dict[OperationKind, OperationHandler] = {}
        for handler in handlers:
            if handler.kind in self._handlers:
                raise ValueError(f"duplicate operation handler: {handler.kind}")
            self._handlers[handler.kind] = handler
        self._runs: deque[OperationRun] = deque(maxlen=history_limit)
        self._execution_lock = asyncio.Lock()
        self._history_lock = asyncio.Lock()

    async def trigger(
        self,
        command: OperationCommand,
        *,
        origin: TriggerOrigin,
        schedule_id: str | None = None,
    ) -> OperationRun:
        handler = self._handlers.get(command.operation)
        if handler is None:
            raise OperationUnavailableError(command.operation.value)
        trace_id = self._current_or_new_trace_id()
        started_at = utc_now()
        running = OperationRun(
            trace_id=trace_id,
            operation=command.operation,
            origin=origin,
            requested_by=command.requested_by,
            schedule_id=schedule_id,
            status=OperationRunStatus.RUNNING,
            started_at=started_at,
        )
        token = set_trace_id(str(trace_id))
        cancellation: asyncio.CancelledError | None = None
        try:
            try:
                async with self._execution_lock:
                    logger.info(
                        "operation started run_id=%s operation=%s origin=%s",
                        running.run_id,
                        running.operation.value,
                        running.origin.value,
                    )
                    try:
                        result = await handler.execute(command)
                    except Exception:
                        logger.exception(
                            "operation failed run_id=%s operation=%s",
                            running.run_id,
                            running.operation.value,
                        )
                        terminal = running.model_copy(
                            update={
                                "status": OperationRunStatus.FAILED,
                                "finished_at": utc_now(),
                                "error": (
                                    "Operation failed; inspect the trace-linked server logs."
                                ),
                            }
                        )
                    else:
                        terminal = running.model_copy(
                            update={
                                "status": OperationRunStatus.SUCCEEDED,
                                "finished_at": utc_now(),
                                "result": result,
                            }
                        )
                        logger.info(
                            "operation succeeded run_id=%s operation=%s",
                            running.run_id,
                            running.operation.value,
                        )
            except asyncio.CancelledError as exc:
                cancellation = exc
                terminal = running.model_copy(
                    update={
                        "status": OperationRunStatus.FAILED,
                        "finished_at": utc_now(),
                        "error": "Operation was cancelled after in-flight work stopped.",
                    }
                )
        finally:
            reset_trace_id(token)
        terminal = OperationRun.model_validate(terminal.model_dump())
        async with self._history_lock:
            self._runs.append(terminal)
        if cancellation is not None:
            raise cancellation
        return terminal

    async def list_runs(self, *, limit: int = 50) -> Sequence[OperationRun]:
        if limit < 1:
            return []
        async with self._history_lock:
            return list(reversed(self._runs))[:limit]

    @staticmethod
    def _current_or_new_trace_id() -> UUID:
        try:
            return UUID(trace_id_var.get())
        except (ValueError, AttributeError):
            return uuid4()


class IntervalScheduler:
    """Small replaceable interval scheduler; it owns no business logic."""

    def __init__(
        self,
        dispatcher: OperationDispatcher,
        *,
        enabled: bool,
        interval_seconds: float,
        poll_interval_seconds: float,
        retention_dry_run: bool,
        schedule_id: str = "retention-cleanup",
    ) -> None:
        self._dispatcher = dispatcher
        self._poll_interval_seconds = poll_interval_seconds
        self._retention_dry_run = retention_dry_run
        self._state = ScheduleSnapshot(
            schedule_id=schedule_id,
            operation=OperationKind.RETENTION_CLEANUP,
            enabled=enabled,
            interval_seconds=interval_seconds,
            next_run_at=(utc_now() + timedelta(seconds=interval_seconds) if enabled else None),
        )
        self._state_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if not self._state.enabled or self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop(), name="god-news-interval-scheduler")
        logger.info("operation scheduler started schedule_id=%s", self._state.schedule_id)

    async def list_schedules(self) -> Sequence[ScheduleSnapshot]:
        async with self._state_lock:
            return [self._state.model_copy(deep=True)]

    async def run_due(self, *, now: datetime | None = None) -> OperationRun | None:
        candidate_now = now or utc_now()
        if candidate_now.tzinfo is None:
            raise ValueError("scheduler timestamps must be timezone-aware")
        resolved_now = candidate_now.astimezone(UTC)
        async with self._state_lock:
            state = self._state
            if not state.enabled or state.next_run_at is None or state.next_run_at > resolved_now:
                return None
            self._state = state.model_copy(
                update={
                    "next_run_at": resolved_now + timedelta(seconds=state.interval_seconds),
                }
            )
        command = RetentionCleanupCommand(
            dry_run=self._retention_dry_run,
            requested_by=f"schedule:{state.schedule_id}",
        )
        run = await self._dispatcher.trigger(
            command,
            origin=TriggerOrigin.SCHEDULE,
            schedule_id=state.schedule_id,
        )
        async with self._state_lock:
            self._state = self._state.model_copy(
                update={"last_run_id": run.run_id, "last_run_status": run.status}
            )
        return run

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_due()
            except Exception:
                logger.exception("scheduler tick failed schedule_id=%s", self._state.schedule_id)
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._poll_interval_seconds,
                )
            except TimeoutError:
                continue

    async def aclose(self) -> None:
        self._stop.set()
        task, self._task = self._task, None
        if task is not None:
            await task
            logger.info("operation scheduler stopped schedule_id=%s", self._state.schedule_id)
