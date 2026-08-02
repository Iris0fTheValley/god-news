from __future__ import annotations

from typing import Protocol

from god_news.domain.runtime_control import (
    RuntimeAction,
    RuntimeCommandReceipt,
    RuntimeControlStatus,
)


class RuntimeController(Protocol):
    async def status(self) -> RuntimeControlStatus: ...

    async def request(self, action: RuntimeAction) -> RuntimeCommandReceipt: ...
