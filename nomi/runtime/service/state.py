"""实例级 runtime service 状态、日志与进程检查。"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from nomi.channel.registry import channel_has_login_state, get_active_channel_kind
from nomi.config.instance import get_instance_name, get_instance_root
from nomi.config.loader import get_config_path
from nomi.config.paths import get_logs_dir
from nomi.providers.factory.resolution import resolve_active_model

SERVICE_LOG_FILENAME = "runtime-service.log"
SERVICE_PID_FILENAME = "runtime-service.pid"
SERVICE_STATE_FILENAME = "runtime-service.json"


@dataclass(frozen=True, slots=True)
class RuntimeServiceState:
    """描述当前实例 runtime service 状态。"""

    state: str
    pid: int | None
    log_path: Path
    pid_path: Path
    state_path: Path
    meta: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RuntimeStatusSnapshot:
    """供 status 命令展示的 runtime 状态快照。"""

    running: bool
    uptime_text: str
    log_path: Path
    pid: int | None
    service_state: str
    remote_enabled: bool
    remote_running: bool
    remote_host: str
    remote_port: int
    channel_enabled: bool
    channel_running: bool
    channel_kind: str | None
    channel_logged_in: bool
    scheduler_owner: str


def get_service_pid_path() -> Path:
    """返回实例 runtime pid 文件路径。"""
    return get_logs_dir() / SERVICE_PID_FILENAME


def get_service_log_path() -> Path:
    """返回实例 runtime 日志路径。"""
    return get_logs_dir() / SERVICE_LOG_FILENAME


def get_service_state_path() -> Path:
    """返回实例 runtime 状态文件路径。"""
    return get_logs_dir() / SERVICE_STATE_FILENAME


def read_service_pid(pid_path: Path | None = None) -> int | None:
    """读取 runtime pid 文件。"""
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
    """读取 runtime 状态文件。"""
    resolved_path = state_path or get_service_state_path()
    if not resolved_path.exists():
        return None
    try:
        raw = json.loads(resolved_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def write_service_state_file(
    *,
    pid: int,
    mode: str,
    config: Any,
    remote_running: bool,
    channel_running: bool,
    channel_status: str = "",
    state_path: Path | None = None,
    log_path: Path | None = None,
) -> Path:
    """写入实例 runtime 状态文件。"""
    resolved_state_path = state_path or get_service_state_path()
    resolved_log_path = log_path or get_service_log_path()
    resolved_state_path.parent.mkdir(parents=True, exist_ok=True)
    channel_kind = str(get_active_channel_kind(config) or "").strip()
    payload = {
        "pid": pid,
        "mode": mode,
        "started_at": time.time(),
        "instance_name": get_instance_name(),
        "instance_root": str(get_instance_root()),
        "config_path": str(get_config_path()),
        "provider": config.agents.defaults.provider,
        "model": resolve_active_model(config),
        "scheduler_owner": "runtime",
        "remote": {
            "enabled": bool(config.remote.enabled),
            "running": bool(remote_running),
            "host": config.remote.host,
            "port": config.remote.port,
        },
        "channel": {
            "enabled": bool(channel_kind),
            "running": bool(channel_running),
            "kind": channel_kind or None,
            "logged_in": (
                channel_has_login_state(config, channel_kind) if channel_kind else False
            ),
            "status": channel_status,
        },
        "log_path": str(resolved_log_path),
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
    """等待子进程写入 runtime 状态文件。"""
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


def cleanup_stale_service_files(
    pid_path: Path | None = None,
    state_path: Path | None = None,
) -> None:
    """清理失效 runtime pid/state 文件。"""
    resolved_pid_path = pid_path or get_service_pid_path()
    resolved_state_path = state_path or get_service_state_path()
    resolved_pid_path.unlink(missing_ok=True)
    resolved_state_path.unlink(missing_ok=True)


def release_service_files_for_pid(
    pid: int,
    *,
    pid_path: Path | None = None,
    state_path: Path | None = None,
) -> None:
    """仅当文件归属当前 pid 时清理 runtime pid/state 文件。"""
    resolved_pid_path = pid_path or get_service_pid_path()
    resolved_state_path = state_path or get_service_state_path()
    if read_service_pid(resolved_pid_path) == pid:
        resolved_pid_path.unlink(missing_ok=True)
    state = read_service_state_file(resolved_state_path)
    if isinstance(state, dict) and int(state.get("pid") or 0) == pid:
        resolved_state_path.unlink(missing_ok=True)


def get_service_state(config: Any | None = None) -> RuntimeServiceState:
    """返回当前实例 runtime service 状态。"""
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
            return RuntimeServiceState("stale", None, log_path, pid_path, state_path, service_meta)
        return RuntimeServiceState("stopped", None, log_path, pid_path, state_path, service_meta)
    if is_process_alive(pid):
        return RuntimeServiceState("running", pid, log_path, pid_path, state_path, service_meta)
    return RuntimeServiceState("stale", pid, log_path, pid_path, state_path, service_meta)


def wait_for_process_exit(pid: int, timeout_seconds: float) -> bool:
    """等待目标进程退出。"""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not is_process_alive(pid):
            return True
        time.sleep(0.1)
    return not is_process_alive(pid)


def build_runtime_status_snapshot(config: Any) -> RuntimeStatusSnapshot:
    """构造统一 runtime 状态快照。"""
    service_state = get_service_state(config)
    meta = service_state.meta or {}
    remote_meta = meta.get("remote") if isinstance(meta.get("remote"), dict) else {}
    channel_meta = meta.get("channel") if isinstance(meta.get("channel"), dict) else {}
    channel_kind = str(get_active_channel_kind(config) or "").strip()
    uptime_text = "-"
    if service_state.pid is not None and service_state.state == "running":
        started_at = _resolve_process_start_time(service_state.pid)
        if started_at is not None:
            duration = datetime.now() - started_at
            seconds = int(duration.total_seconds())
            hours, remainder = divmod(seconds, 3600)
            minutes, secs = divmod(remainder, 60)
            uptime_text = f"{hours}h {minutes}m {secs}s"
    return RuntimeStatusSnapshot(
        running=service_state.state == "running",
        uptime_text=uptime_text,
        log_path=service_state.log_path,
        pid=service_state.pid,
        service_state=service_state.state,
        remote_enabled=bool(config.remote.enabled),
        remote_running=bool(remote_meta.get("running")) and service_state.state == "running",
        remote_host=str(remote_meta.get("host") or config.remote.host),
        remote_port=int(remote_meta.get("port") or config.remote.port),
        channel_enabled=bool(channel_kind),
        channel_running=bool(channel_meta.get("running")) and service_state.state == "running",
        channel_kind=channel_kind or None,
        channel_logged_in=(
            channel_has_login_state(config, channel_kind) if channel_kind else False
        ),
        scheduler_owner=str(meta.get("scheduler_owner") or "-"),
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
