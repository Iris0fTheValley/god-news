from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from god_news.api.routes import router
from god_news.api.schemas import ProblemDetail
from god_news.config import Settings, get_settings
from god_news.container import AppContainer, build_container
from god_news.errors import GodNewsError
from god_news.logging import configure_logging, reset_trace_id, set_trace_id, trace_id_var

logger = logging.getLogger(__name__)
ContainerFactory = Callable[[Settings], Awaitable[AppContainer]]


def create_app(
    settings: Settings | None = None,
    *,
    container_factory: ContainerFactory = build_container,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = await container_factory(resolved_settings)
        app.state.container = container
        try:
            yield
        finally:
            await container.aclose()

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        description="Review-gated multilingual content-to-audio pipeline.",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def trace_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        candidate = request.headers.get("X-Trace-ID")
        try:
            trace_id = str(UUID(candidate)) if candidate else str(uuid4())
        except ValueError:
            trace_id = str(uuid4())
        token = set_trace_id(trace_id)
        try:
            response = await call_next(request)
            response.headers["X-Trace-ID"] = trace_id
            return response
        finally:
            reset_trace_id(token)

    @app.exception_handler(GodNewsError)
    async def handle_domain_error(request: Request, exc: GodNewsError) -> JSONResponse:
        del request
        logger.warning("request failed: %s", exc.code)
        problem = ProblemDetail(
            code=exc.code,
            message=exc.public_message,
            trace_id=trace_id_var.get(),
            story_id=exc.story_id,
        )
        return JSONResponse(status_code=exc.status_code, content=problem.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        del request, exc
        problem = ProblemDetail(
            code="request_validation_failed",
            message="Request did not match the required schema.",
            trace_id=trace_id_var.get(),
        )
        return JSONResponse(status_code=422, content=problem.model_dump(mode="json"))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        del request
        logger.exception("unhandled request failure", exc_info=exc)
        problem = ProblemDetail(
            code="internal_error",
            message="An unexpected internal error occurred.",
            trace_id=trace_id_var.get(),
        )
        return JSONResponse(status_code=500, content=problem.model_dump(mode="json"))

    app.include_router(router, prefix="/api/v1")
    return app
