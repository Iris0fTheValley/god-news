from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from god_news.api.app import create_app
from god_news.domain.runtime_control import RuntimeAction, RuntimeCommand
from god_news.errors import RuntimeControlConflictError, RuntimeControlUnavailableError
from god_news.infrastructure.runtime_control import FileRuntimeController

from .conftest import Stack

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _available_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.mark.asyncio
async def test_runtime_controller_writes_one_atomic_supervisor_command(tmp_path: Path) -> None:
    path = tmp_path / "control" / "command.json"
    controller = FileRuntimeController(
        command_path=path,
        enabled=True,
        supervised=True,
        process_id=4321,
    )

    status = await controller.status()
    assert status.enabled
    assert status.supervised
    assert status.pending_action is None

    receipt = await controller.request(RuntimeAction.RESTART)
    command = RuntimeCommand.model_validate_json(path.read_text(encoding="utf-8"))
    assert receipt.command_id == command.command_id
    assert command.action is RuntimeAction.RESTART
    assert command.process_id == 4321
    assert (await controller.status()).pending_action is RuntimeAction.RESTART

    with pytest.raises(RuntimeControlConflictError):
        await controller.request(RuntimeAction.SHUTDOWN)


@pytest.mark.asyncio
async def test_runtime_controller_fails_closed_without_supervisor(tmp_path: Path) -> None:
    controller = FileRuntimeController(
        command_path=tmp_path / "command.json",
        enabled=True,
        supervised=False,
    )

    with pytest.raises(RuntimeControlUnavailableError):
        await controller.request(RuntimeAction.RESTART)


@pytest.mark.asyncio
async def test_runtime_api_is_loopback_only_and_returns_accepted(
    stack: Stack,
    tmp_path: Path,
) -> None:
    command_path = tmp_path / "command.json"
    stack.container.runtime_control = FileRuntimeController(
        command_path=command_path,
        enabled=True,
        supervised=True,
        process_id=8765,
    )

    async def factory(settings):  # type: ignore[no-untyped-def]
        del settings
        return stack.container

    app = create_app(stack.settings, container_factory=factory)
    async with app.router.lifespan_context(app):
        local_transport = httpx.ASGITransport(
            app=app,
            raise_app_exceptions=False,
            client=("127.0.0.1", 51000),
        )
        async with httpx.AsyncClient(
            transport=local_transport,
            base_url="http://test",
        ) as client:
            status_response = await client.get("/api/v1/system/runtime")
            action_response = await client.post("/api/v1/system/runtime/restart")

        remote_transport = httpx.ASGITransport(
            app=app,
            raise_app_exceptions=False,
            client=("203.0.113.10", 51001),
        )
        async with httpx.AsyncClient(
            transport=remote_transport,
            base_url="http://test",
        ) as client:
            forbidden_response = await client.get("/api/v1/system/runtime")

    assert status_response.status_code == 200
    assert status_response.json()["process_id"] == 8765
    assert action_response.status_code == 202
    assert action_response.json()["action"] == "restart"
    assert forbidden_response.status_code == 403
    assert forbidden_response.json()["code"] == "runtime_control_forbidden"


def test_foreground_backend_returns_restart_exit_code(tmp_path: Path) -> None:
    port = _available_loopback_port()
    command_path = tmp_path / "runtime-command.json"
    environment = os.environ.copy()
    environment.update(
        {
            "GOD_NEWS_RUNTIME_CONTROL_ENABLED": "true",
            "GOD_NEWS_RUNTIME_CONTROL_SUPERVISED": "true",
            "GOD_NEWS_RUNTIME_CONTROL_COMMAND_PATH": str(command_path),
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "scripts/dev/run_backend.py",
            "--app",
            "god_news.demo.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--command-path",
            str(command_path),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail(f"foreground backend exited early with code {process.returncode}")
            try:
                response = httpx.get(f"{base_url}/api/v1/system/runtime", timeout=0.5)
            except httpx.HTTPError:
                time.sleep(0.1)
                continue
            if response.status_code == 200:
                break
            time.sleep(0.1)
        else:
            pytest.fail("foreground backend did not become ready")

        response = httpx.post(f"{base_url}/api/v1/system/runtime/restart", timeout=2)
        assert response.status_code == 202
        assert process.wait(timeout=15) == 75
        command = RuntimeCommand.model_validate_json(command_path.read_text(encoding="utf-8"))
        assert command.action is RuntimeAction.RESTART
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
