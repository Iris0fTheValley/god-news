from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from god_news.api.dependencies import get_container
from god_news.api.schemas import ProblemDetail
from god_news.application.source_runs import SourceRunService
from god_news.application.source_schedule import SourceCollectionScheduler
from god_news.container import AppContainer
from god_news.errors import ConfigurationError
from god_news.logging import trace_id_var
from god_news.sources.collectors.models import CollectorDiagnostic
from god_news.sources.models import SourceName
from god_news.sources.run_models import (
    SourceRun,
    SourceRunReadiness,
    SourceRunRequest,
    SourceRunStatus,
)
from god_news.sources.schedule_models import SourceScheduleSnapshot

PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
    429: {"model": ProblemDetail},
    503: {"model": ProblemDetail},
}
router = APIRouter(responses=PROBLEM_RESPONSES, tags=["source-runs"])
ContainerDependency = Annotated[AppContainer, Depends(get_container)]


def _service(container: AppContainer) -> SourceRunService:
    if container.source_runs is None:
        raise ConfigurationError("Source collection runs are not configured.")
    return container.source_runs


def _scheduler(container: AppContainer) -> SourceCollectionScheduler:
    if container.source_scheduler is None:
        raise ConfigurationError("Automatic source collection is not configured.")
    return container.source_scheduler


@router.get(
    "/sources/collectors",
    response_model=SourceRunReadiness,
    operation_id="getSourceCollectorReadiness",
)
async def collector_readiness(container: ContainerDependency) -> SourceRunReadiness:
    return SourceRunReadiness(collectors=list(_service(container).readiness()))


@router.post(
    "/sources/{source}/diagnostics",
    response_model=CollectorDiagnostic,
    operation_id="runSourceDiagnostic",
)
async def run_source_diagnostic(
    source: SourceName,
    container: ContainerDependency,
) -> CollectorDiagnostic:
    return await _service(container).diagnose(source)


@router.get(
    "/source-schedule",
    response_model=SourceScheduleSnapshot,
    operation_id="getSourceSchedule",
)
async def get_source_schedule(container: ContainerDependency) -> SourceScheduleSnapshot:
    return await _scheduler(container).snapshot()


@router.post(
    "/source-schedule/start",
    response_model=SourceScheduleSnapshot,
    operation_id="startSourceSchedule",
)
async def start_source_schedule(container: ContainerDependency) -> SourceScheduleSnapshot:
    return await _scheduler(container).enable()


@router.post(
    "/source-schedule/stop",
    response_model=SourceScheduleSnapshot,
    operation_id="stopSourceSchedule",
)
async def stop_source_schedule(container: ContainerDependency) -> SourceScheduleSnapshot:
    return await _scheduler(container).disable()


@router.post(
    "/source-runs",
    response_model=SourceRun,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="startSourceRun",
)
async def start_source_run(
    request: SourceRunRequest,
    container: ContainerDependency,
) -> SourceRun:
    return await _service(container).start(request, trace_id=UUID(trace_id_var.get()))


@router.get(
    "/source-runs",
    response_model=list[SourceRun],
    operation_id="listSourceRuns",
)
async def list_source_runs(
    container: ContainerDependency,
    source: SourceName | None = None,
    run_status: SourceRunStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SourceRun]:
    return list(
        await _service(container).list(
            source=source,
            status=run_status,
            limit=limit,
            offset=offset,
        )
    )


@router.get(
    "/source-runs/{run_id}",
    response_model=SourceRun,
    operation_id="getSourceRun",
)
async def get_source_run(run_id: UUID, container: ContainerDependency) -> SourceRun:
    return await _service(container).get(run_id)


@router.post(
    "/source-runs/{run_id}/cancel",
    response_model=SourceRun,
    operation_id="cancelSourceRun",
)
async def cancel_source_run(run_id: UUID, container: ContainerDependency) -> SourceRun:
    return await _service(container).cancel(run_id)
