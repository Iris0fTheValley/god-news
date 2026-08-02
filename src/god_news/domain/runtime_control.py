from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from god_news.domain.models import DomainModel, utc_now


class RuntimeAction(StrEnum):
    RESTART = "restart"
    SHUTDOWN = "shutdown"


class RuntimeControlStatus(DomainModel):
    enabled: bool
    supervised: bool
    process_id: int = Field(gt=0)
    pending_action: RuntimeAction | None = None


class RuntimeCommand(DomainModel):
    command_id: UUID = Field(default_factory=uuid4)
    action: RuntimeAction
    process_id: int = Field(gt=0)
    requested_at: datetime = Field(default_factory=utc_now)


class RuntimeCommandReceipt(DomainModel):
    command_id: UUID
    action: RuntimeAction
    accepted_at: datetime
    process_id: int = Field(gt=0)
