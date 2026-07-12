from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Liveness(ApiModel):
    alive: bool = True


class ProblemDetail(ApiModel):
    code: str
    message: str
    trace_id: str
    story_id: UUID | None = None
