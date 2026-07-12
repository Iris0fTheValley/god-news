from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from god_news.api.dependencies import get_container
from god_news.api.schemas import ProblemDetail
from god_news.container import AppContainer
from god_news.errors import ConfigurationError
from god_news.operations.models import (
    OperationRun,
    RetentionCleanupCommand,
    RoleProfile,
    RoleProfileCreate,
    RoleProfileDelete,
    RoleProfileReplace,
    ScheduleSnapshot,
    TriggerOrigin,
)
from god_news.operations.roles import RoleProfileService
from god_news.operations.scheduler import OperationDispatcher

PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetail},
    409: {"model": ProblemDetail},
    422: {"model": ProblemDetail},
    503: {"model": ProblemDetail},
}
router = APIRouter(responses=PROBLEM_RESPONSES)
ContainerDependency = Annotated[AppContainer, Depends(get_container)]


def _roles(container: AppContainer) -> RoleProfileService:
    if container.role_profiles is None:
        raise ConfigurationError("Role profile storage is not configured.")
    return container.role_profiles


def _operations(container: AppContainer) -> OperationDispatcher:
    if container.operations is None:
        raise ConfigurationError("Operational task execution is not configured.")
    return container.operations


@router.post("/roles", response_model=RoleProfile, status_code=status.HTTP_201_CREATED)
async def create_role(request: RoleProfileCreate, container: ContainerDependency) -> RoleProfile:
    return await _roles(container).create(request)


@router.get("/roles", response_model=list[RoleProfile])
async def list_roles(
    container: ContainerDependency,
    enabled: Annotated[bool | None, Query()] = None,
) -> list[RoleProfile]:
    return list(await _roles(container).list(enabled=enabled))


@router.get("/roles/{profile_id}", response_model=RoleProfile)
async def get_role(profile_id: UUID, container: ContainerDependency) -> RoleProfile:
    return await _roles(container).get(profile_id)


@router.put("/roles/{profile_id}", response_model=RoleProfile)
async def replace_role(
    profile_id: UUID,
    request: RoleProfileReplace,
    container: ContainerDependency,
) -> RoleProfile:
    return await _roles(container).replace(profile_id, request)


@router.delete("/roles/{profile_id}", response_model=RoleProfile)
async def delete_role(
    profile_id: UUID,
    request: RoleProfileDelete,
    container: ContainerDependency,
) -> RoleProfile:
    return await _roles(container).delete(
        profile_id,
        expected_version=request.expected_version,
    )


@router.post("/operations/retention/runs", response_model=OperationRun)
async def run_retention(
    command: RetentionCleanupCommand,
    container: ContainerDependency,
) -> OperationRun:
    return await _operations(container).trigger(command, origin=TriggerOrigin.MANUAL)


@router.get("/operations/runs", response_model=list[OperationRun])
async def list_operation_runs(
    container: ContainerDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[OperationRun]:
    return list(await _operations(container).list_runs(limit=limit))


@router.get("/operations/schedules", response_model=list[ScheduleSnapshot])
async def list_operation_schedules(container: ContainerDependency) -> list[ScheduleSnapshot]:
    if container.operation_scheduler is None:
        return []
    return list(await container.operation_scheduler.list_schedules())
