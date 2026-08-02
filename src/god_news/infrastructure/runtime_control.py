from __future__ import annotations

import asyncio
import os
from pathlib import Path

from god_news.domain.runtime_control import (
    RuntimeAction,
    RuntimeCommand,
    RuntimeCommandReceipt,
    RuntimeControlStatus,
)
from god_news.errors import RuntimeControlConflictError, RuntimeControlUnavailableError


class FileRuntimeController:
    """Atomically hands a lifecycle command to the foreground dev supervisor."""

    def __init__(
        self,
        *,
        command_path: Path,
        enabled: bool,
        supervised: bool,
        process_id: int | None = None,
    ) -> None:
        self._command_path = command_path.expanduser().resolve(strict=False)
        self._enabled = enabled
        self._supervised = supervised
        self._process_id = process_id or os.getpid()
        self._lock = asyncio.Lock()

    async def status(self) -> RuntimeControlStatus:
        pending = await asyncio.to_thread(self._read_pending_action)
        return RuntimeControlStatus(
            enabled=self._enabled,
            supervised=self._supervised,
            process_id=self._process_id,
            pending_action=pending,
        )

    async def request(self, action: RuntimeAction) -> RuntimeCommandReceipt:
        if not self._enabled or not self._supervised:
            raise RuntimeControlUnavailableError()
        command = RuntimeCommand(action=action, process_id=self._process_id)
        async with self._lock:
            if self._command_path.exists():
                raise RuntimeControlConflictError()
            await asyncio.to_thread(self._write_command, command)
        return RuntimeCommandReceipt(
            command_id=command.command_id,
            action=command.action,
            accepted_at=command.requested_at,
            process_id=command.process_id,
        )

    def _read_pending_action(self) -> RuntimeAction | None:
        if not self._command_path.is_file():
            return None
        try:
            command = RuntimeCommand.model_validate_json(
                self._command_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None
        if command.process_id != self._process_id:
            return None
        return command.action

    def _write_command(self, command: RuntimeCommand) -> None:
        self._command_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._command_path.with_name(
            f".{self._command_path.name}.{command.command_id}.tmp"
        )
        try:
            temporary.write_text(command.model_dump_json(), encoding="utf-8")
            temporary.replace(self._command_path)
        finally:
            temporary.unlink(missing_ok=True)
