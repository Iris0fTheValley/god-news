from __future__ import annotations

import asyncio
import ctypes
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TypeVar

import psutil
from pydantic import BaseModel

ResponseT = TypeVar("ResponseT", bound=BaseModel)


def sanitized_subprocess_env() -> dict[str, str]:
    allowed = (
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "LANG",
        "LC_ALL",
    )
    result = {name: os.environ[name] for name in allowed if name in os.environ}
    result["PYTHONIOENCODING"] = "utf-8"
    result["PYTHONUNBUFFERED"] = "1"
    return result


def attach_kill_on_close_job(pid: int) -> int | None:
    """Put a Windows subprocess tree in a kill-on-close Job Object."""
    if os.name != "nt":
        return None
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.OpenProcess.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    information = ExtendedLimitInformation()
    information.BasicLimitInformation.LimitFlags = 0x00002000
    configured = kernel32.SetInformationJobObject(
        job,
        9,
        ctypes.byref(information),
        ctypes.sizeof(information),
    )
    process_handle = kernel32.OpenProcess(0x0101, False, pid)
    assigned = bool(
        process_handle and configured and kernel32.AssignProcessToJobObject(job, process_handle)
    )
    if process_handle:
        kernel32.CloseHandle(process_handle)
    if not assigned:
        kernel32.CloseHandle(job)
        return None
    return int(job)


def close_kill_on_close_job(handle: int | None) -> None:
    if handle is None or os.name != "nt":
        return
    ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle)


def _snapshot_children(pid: int) -> list[psutil.Process]:
    try:
        return psutil.Process(pid).children(recursive=True)
    except psutil.Error:
        return []


def _terminate_captured_processes(
    processes: Sequence[psutil.Process],
    grace_seconds: float,
) -> None:
    for child in reversed(processes):
        try:
            child.terminate()
        except psutil.Error:
            continue
    _, alive = psutil.wait_procs(list(processes), timeout=grace_seconds)
    for child in alive:
        try:
            child.kill()
        except psutil.Error:
            continue
    if alive:
        psutil.wait_procs(alive, timeout=grace_seconds)


async def terminate_process_tree(
    process: asyncio.subprocess.Process,
    *,
    grace_seconds: float = 5.0,
) -> None:
    children = await asyncio.to_thread(_snapshot_children, process.pid)
    if process.returncode is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=grace_seconds)
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
    await asyncio.to_thread(_terminate_captured_processes, children, grace_seconds)


async def run_json_worker(
    *,
    command: Sequence[str],
    request: BaseModel,
    response_type: type[ResponseT],
    timeout_seconds: float,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    max_stdout_bytes: int | None = None,
) -> ResponseT:
    if not command:
        raise ValueError("worker command cannot be empty")
    creationflags = 0
    if os.name == "nt":
        creationflags = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd) if cwd else None,
        env=dict(env) if env else sanitized_subprocess_env(),
        creationflags=creationflags,
    )
    job_handle = await asyncio.to_thread(attach_kill_on_close_job, process.pid)
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(request.model_dump_json().encode("utf-8")),
            timeout=timeout_seconds,
        )
    except (TimeoutError, asyncio.CancelledError):
        await asyncio.shield(terminate_process_tree(process))
        raise
    finally:
        await asyncio.to_thread(close_kill_on_close_job, job_handle)
    if max_stdout_bytes is not None and len(stdout) > max_stdout_bytes:
        raise RuntimeError("worker response exceeded the configured output limit")
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace")[-4_000:]
        raise RuntimeError(f"worker exited with code {process.returncode}: {detail}")
    return response_type.model_validate_json(stdout)
