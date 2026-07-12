from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import psutil
import pytest
from pydantic import BaseModel, ConfigDict

from god_news.infrastructure.processes import run_json_worker


class WorkerMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


@pytest.mark.asyncio
async def test_json_worker_round_trip_and_hard_timeout() -> None:
    response = await run_json_worker(
        command=(sys.executable, "-c", "import sys; print(sys.stdin.read())"),
        request=WorkerMessage(value=7),
        response_type=WorkerMessage,
        timeout_seconds=5,
    )
    assert response.value == 7

    started = time.monotonic()
    with pytest.raises(TimeoutError):
        await run_json_worker(
            command=(sys.executable, "-c", "import time; time.sleep(30)"),
            request=WorkerMessage(value=1),
            response_type=WorkerMessage,
            timeout_seconds=0.1,
        )
    assert time.monotonic() - started < 5


@pytest.mark.asyncio
async def test_timeout_reaps_worker_child_process(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    script = (
        "import pathlib, subprocess, sys, time; "
        "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(30)"
    )
    with pytest.raises(TimeoutError):
        await run_json_worker(
            command=(sys.executable, "-c", script, str(pid_file)),
            request=WorkerMessage(value=1),
            response_type=WorkerMessage,
            timeout_seconds=0.5,
        )
    child_pid = int(pid_file.read_text())
    for _ in range(20):
        if not psutil.pid_exists(child_pid):
            break
        await asyncio.sleep(0.1)
    assert not psutil.pid_exists(child_pid)
