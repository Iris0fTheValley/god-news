from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from uuid import UUID

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")
story_id_var: ContextVar[str] = ContextVar("story_id", default="-")


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_var.get()
        record.story_id = story_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", "-"),
            "story_id": getattr(record, "story_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def set_trace_id(trace_id: str) -> Token[str]:
    return trace_id_var.set(trace_id)


def reset_trace_id(token: Token[str]) -> None:
    trace_id_var.reset(token)


@contextmanager
def story_log_context(story_id: UUID) -> Iterator[None]:
    token = story_id_var.set(str(story_id))
    try:
        yield
    finally:
        story_id_var.reset(token)
