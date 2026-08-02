from __future__ import annotations

import ipaddress
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from god_news.api.dependencies import get_container
from god_news.api.schemas import ProblemDetail
from god_news.container import AppContainer
from god_news.domain.runtime_control import (
    RuntimeAction,
    RuntimeCommandReceipt,
    RuntimeControlStatus,
)
from god_news.domain.runtime_control_ports import RuntimeController
from god_news.errors import ConfigurationError, RuntimeControlForbiddenError

router = APIRouter(
    prefix="/system/runtime",
    tags=["runtime"],
    responses={
        403: {"model": ProblemDetail},
        409: {"model": ProblemDetail},
        503: {"model": ProblemDetail},
    },
)
ContainerDependency = Annotated[AppContainer, Depends(get_container)]


def _controller(container: ContainerDependency) -> RuntimeController:
    if container.runtime_control is None:
        raise ConfigurationError("Runtime control is not configured.")
    return container.runtime_control


RuntimeControllerDependency = Annotated[RuntimeController, Depends(_controller)]


def _require_loopback(request: Request) -> None:
    client = request.client
    if client is None:
        raise RuntimeControlForbiddenError()
    try:
        if not ipaddress.ip_address(client.host).is_loopback:
            raise RuntimeControlForbiddenError()
    except ValueError as exc:
        raise RuntimeControlForbiddenError() from exc


@router.get("", response_model=RuntimeControlStatus, operation_id="getRuntimeControlStatus")
async def get_runtime_control_status(
    request: Request,
    controller: RuntimeControllerDependency,
) -> RuntimeControlStatus:
    _require_loopback(request)
    return await controller.status()


@router.post(
    "/{action}",
    response_model=RuntimeCommandReceipt,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="requestRuntimeAction",
)
async def request_runtime_action(
    action: RuntimeAction,
    request: Request,
    controller: RuntimeControllerDependency,
) -> RuntimeCommandReceipt:
    _require_loopback(request)
    return await controller.request(action)
