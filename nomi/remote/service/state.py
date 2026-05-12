"""旧 remote 独立 service pid 检测与启动前校验。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from nomi.config.paths import get_logs_dir

SERVICE_LOG_FILENAME = "remote-service.log"
SERVICE_PID_FILENAME = "remote-service.pid"
SERVICE_STATE_FILENAME = "remote-service.json"


@dataclass(frozen=True, slots=True)
class RemoteServiceState:
    """描述旧 remote 独立 service 状态。"""

    state: str
    pid: int | None
    log_path: Path
    pid_path: Path
    state_path: Path


def get_service_pid_path() -> Path:
    """返回旧 remote service pid 文件路径。"""
    return get_logs_dir() / SERVICE_PID_FILENAME


def get_service_log_path() -> Path:
    """返回旧 remote service 日志路径。"""
    return get_logs_dir() / SERVICE_LOG_FILENAME


def get_service_state_path() -> Path:
    """返回旧 remote service 状态文件路径。"""
    return get_logs_dir() / SERVICE_STATE_FILENAME


def read_service_pid(pid_path: Path | None = None) -> int | None:
    """读取旧 remote service pid 文件。"""
    resolved_path = pid_path or get_service_pid_path()
    if not resolved_path.exists():
        return None
    try:
        return int(resolved_path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def is_process_alive(pid: int) -> bool:
    """判断进程是否存活。"""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_service_state_file(state_path: Path | None = None) -> dict[str, Any] | None:
    """读取旧 remote service 状态文件。"""
    resolved_path = state_path or get_service_state_path()
    if not resolved_path.exists():
        return None
    try:
        raw = json.loads(resolved_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def get_service_state(config: Any | None = None) -> RemoteServiceState:
    """返回旧 remote 独立 service 状态，用于统一 runtime 启动前冲突检测。"""
    del config
    pid_path = get_service_pid_path()
    log_path = get_service_log_path()
    state_path = get_service_state_path()
    service_meta = read_service_state_file(state_path)
    pid = None
    if isinstance(service_meta, dict):
        try:
            pid = int(service_meta.get("pid") or 0) or None
        except (TypeError, ValueError):
            pid = None
    if pid is None:
        pid = read_service_pid(pid_path)
    if pid is None:
        if service_meta is not None or pid_path.exists():
            return RemoteServiceState("stale", None, log_path, pid_path, state_path)
        return RemoteServiceState("stopped", None, log_path, pid_path, state_path)
    if is_process_alive(pid):
        return RemoteServiceState("running", pid, log_path, pid_path, state_path)
    return RemoteServiceState("stale", pid, log_path, pid_path, state_path)


def validate_remote_ready(config) -> None:
    """校验 remote adapter 启动前提。"""
    if not config.remote.enabled:
        raise typer.BadParameter("当前未启用 remote。\n请先运行：nomi remote enable")
    if not str(config.remote.auth_token or "").strip():
        raise typer.BadParameter("当前 remote token 为空。\n请先运行：nomi remote token")
