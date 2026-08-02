from __future__ import annotations

import argparse
import asyncio
import os
from contextlib import suppress
from pathlib import Path

import uvicorn

from god_news.domain.runtime_control import RuntimeAction, RuntimeCommand

RESTART_EXIT_CODE = 75


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Foreground god-news development backend")
    parser.add_argument("--app", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--command-path", type=Path, required=True)
    return parser.parse_args()


def _consume_command(command_path: Path) -> RuntimeCommand | None:
    if not command_path.is_file():
        return None
    try:
        return RuntimeCommand.model_validate_json(
            command_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        command_path.unlink(missing_ok=True)
        return None


async def _watch_commands(
    server: uvicorn.Server,
    command_path: Path,
) -> RuntimeAction | None:
    while not server.should_exit:
        command = await asyncio.to_thread(_consume_command, command_path)
        if command is not None and command.process_id == os.getpid():
            server.should_exit = True
            return command.action
        await asyncio.sleep(0.2)
    return None


async def _serve(args: argparse.Namespace) -> int:
    command_path = args.command_path.expanduser().resolve(strict=False)
    command_path.parent.mkdir(parents=True, exist_ok=True)
    command_path.unlink(missing_ok=True)
    config = uvicorn.Config(
        args.app,
        host=args.host,
        port=args.port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    watcher = asyncio.create_task(_watch_commands(server, command_path))
    action: RuntimeAction | None = None
    try:
        done, _ = await asyncio.wait(
            {server_task, watcher},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if watcher.done() and not watcher.cancelled():
            action = watcher.result()
        if action is not None and not server_task.done():
            await server_task
        elif server_task not in done:
            await server_task
    finally:
        server.should_exit = True
        if not server_task.done():
            server_task.cancel()
            with suppress(asyncio.CancelledError):
                await server_task
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
    return RESTART_EXIT_CODE if action is RuntimeAction.RESTART else 0


def main() -> None:
    raise SystemExit(asyncio.run(_serve(_arguments())))


if __name__ == "__main__":
    main()
