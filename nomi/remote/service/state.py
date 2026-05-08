"""remote service 状态、占用信息与进程检查。"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import typer

from nomi.config.paths import get_logs_dir

SERVICE_LOG_FILENAME = "remote-service.log"
SERVICE_PID_FILENAME = "remote-service.pid"
SERVICE_STATE_FILENAME = "remote-service.json"


@dataclass(frozen=True, slots=True)
class RemoteServiceState:
    """描述当前 remote service 状态。"""

    state: str
    pid: int | None
    log_path: Path
    pid_path: Path
    state_path: Path


@dataclass(frozen=True, slots=True)
class RemoteStatusSnapshot:
    """供 status 命令展示的 remote 状态快照。"""

    enabled: bool
    running: bool
    uptime_text: str
    log_path: Path
    pid: int | None
    service_state: str
    host: str
    port: int


def get_service_pid_path() -> Path:
    """返回后台 service pid 文件路径。"""
    return get_logs_dir() / SERVICE_PID_FILENAME


def get_service_log_path() -> Path:
    """返回后台 service 日志路径。"""
    return get_logs_dir() / SERVICE_LOG_FILENAME


def get_service_state_path() -> Path:
    """返回后台 service 状态文件路径。"""
    return get_logs_dir() / SERVICE_STATE_FILENAME


def read_service_pid(pid_path: Path | None = None) -> int | None:
    """读取 pid 文件。"""
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
    """读取后台 service 状态文件。"""
    resolved_path = state_path or get_service_state_path()
    if not resolved_path.exists():
        return None
    try:
        raw = json.loads(resolved_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def write_service_state_file(
    *,
    pid: int,
    mode: str,
    state_path: Path | None = None,
    log_path: Path | None = None,
) -> Path:
    """写入后台 service 状态文件。"""
    resolved_state_path = state_path or get_service_state_path()
    resolved_state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": pid,
        "mode": mode,
        "log_path": str(log_path or get_service_log_path()),
        "started_at": time.time(),
    }
    resolved_state_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return resolved_state_path


def wait_for_service_registration(
    *,
    pid: int,
    timeout_seconds: float,
    state_path: Path | None = None,
) -> dict[str, Any] | None:
    """等待子进程写入 service 状态文件。"""
    resolved_state_path = state_path or get_service_state_path()
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        state = read_service_state_file(resolved_state_path)
        if isinstance(state, dict) and int(state.get("pid") or 0) == pid:
            return state
        if not is_process_alive(pid):
            return None
        time.sleep(0.1)
    state = read_service_state_file(resolved_state_path)
    if isinstance(state, dict) and int(state.get("pid") or 0) == pid:
        return state
    return None


def cleanup_stale_pid_file(pid_path: Path | None = None) -> None:
    """清理失效 pid 文件。"""
    resolved_path = pid_path or get_service_pid_path()
    if resolved_path.exists():
        resolved_path.unlink()


def cleanup_service_state_file(state_path: Path | None = None) -> None:
    """清理失效 service 状态文件。"""
    resolved_path = state_path or get_service_state_path()
    if resolved_path.exists():
        resolved_path.unlink()


def cleanup_stale_service_files(
    pid_path: Path | None = None,
    state_path: Path | None = None,
) -> None:
    """清理失效的 service pid/state 文件。"""
    cleanup_stale_pid_file(pid_path)
    cleanup_service_state_file(state_path)


def release_service_files_for_pid(
    pid: int,
    *,
    pid_path: Path | None = None,
    state_path: Path | None = None,
) -> None:
    """仅当文件归属当前 pid 时清理 service 文件。"""
    resolved_pid_path = pid_path or get_service_pid_path()
    resolved_state_path = state_path or get_service_state_path()

    existing_pid = read_service_pid(resolved_pid_path)
    if existing_pid == pid:
        cleanup_stale_pid_file(resolved_pid_path)

    state = read_service_state_file(resolved_state_path)
    if isinstance(state, dict) and int(state.get("pid") or 0) == pid:
        cleanup_service_state_file(resolved_state_path)


def get_service_state(config: Any | None = None) -> RemoteServiceState:
    """返回当前 remote service 状态。"""
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
    """校验 remote 启动前提。"""
    if not config.remote.enabled:
        raise typer.BadParameter("当前未启用 remote。\n请先在配置中设置 `remote.enabled=true`。")
    if not str(config.remote.auth_token or "").strip():
        raise typer.BadParameter(
            "当前 remote.auth_token 为空。\n请先在配置中设置 `remote.auth_token`。"
        )


def wait_for_process_exit(pid: int, timeout_seconds: float) -> bool:
    """等待目标进程退出。"""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not is_process_alive(pid):
            return True
        time.sleep(0.1)
    return not is_process_alive(pid)


def build_remote_status_snapshot(config) -> RemoteStatusSnapshot:
    """构造 remote 状态快照。"""
    service_state = get_service_state(config)
    uptime_text = "-"
    if service_state.pid is not None and service_state.state == "running":
        started_at = _resolve_process_start_time(service_state.pid)
        if started_at is not None:
            duration = datetime.now() - started_at
            seconds = int(duration.total_seconds())
            hours, remainder = divmod(seconds, 3600)
            minutes, secs = divmod(remainder, 60)
            uptime_text = f"{hours}h {minutes}m {secs}s"
    return RemoteStatusSnapshot(
        enabled=bool(config.remote.enabled),
        running=service_state.state == "running",
        uptime_text=uptime_text,
        log_path=service_state.log_path,
        pid=service_state.pid,
        service_state=service_state.state,
        host=config.remote.host,
        port=config.remote.port,
    )


def _resolve_process_start_time(pid: int) -> datetime | None:
    """解析目标进程的启动时间。"""
    try:
        return datetime.fromtimestamp(Path(f"/proc/{pid}").stat().st_ctime)
    except Exception:
        try:
            output = subprocess.check_output(
                ["ps", "-p", str(pid), "-o", "lstart="],
                text=True,
            ).strip()
        except Exception:
            return None
        if not output:
            return None
        try:
            return datetime.strptime(output, "%a %b %d %H:%M:%S %Y")
        except ValueError:
            return None
