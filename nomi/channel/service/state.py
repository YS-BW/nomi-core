"""旧 channel 独立 service pid 检测与 channel 配置校验。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from nomi.channel.registry import get_active_channel_kind, get_channel_spec
from nomi.config.paths import get_logs_dir

SERVICE_LOG_FILENAME = "channels-service.log"
SERVICE_PID_FILENAME = "channels-service.pid"
SERVICE_STATE_FILENAME = "channels-service.json"


@dataclass(frozen=True, slots=True)
class ChannelServiceState:
    """描述旧 channel 独立 service 状态。"""

    owner: str | None
    state: str
    pid: int | None
    log_path: Path
    pid_path: Path
    state_path: Path


def get_service_pid_path() -> Path:
    """返回旧 channel service pid 文件路径。"""
    return get_logs_dir() / SERVICE_PID_FILENAME


def get_service_log_path() -> Path:
    """返回旧 channel service 日志路径。"""
    return get_logs_dir() / SERVICE_LOG_FILENAME


def get_service_state_path() -> Path:
    """返回旧 channel service 状态文件路径。"""
    return get_logs_dir() / SERVICE_STATE_FILENAME


def read_service_pid(pid_path: Path | None = None) -> int | None:
    """读取旧 channel service pid 文件。"""
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
    """读取旧 channel service 状态文件。"""
    resolved_path = state_path or get_service_state_path()
    if not resolved_path.exists():
        return None
    try:
        raw = json.loads(resolved_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def get_service_state(config: Any | None = None) -> ChannelServiceState:
    """返回旧 channel 独立 service 状态，用于统一 runtime 启动前冲突检测。"""
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
    owner = None
    if isinstance(service_meta, dict):
        owner = str(service_meta.get("owner", "") or "").strip() or None
    if config is not None:
        kind = str(get_active_channel_kind(config) or "").strip()
        owner = kind or None
    if pid is None:
        if service_meta is not None or pid_path.exists():
            return ChannelServiceState(owner, "stale", None, log_path, pid_path, state_path)
        return ChannelServiceState(owner, "stopped", None, log_path, pid_path, state_path)
    if is_process_alive(pid):
        return ChannelServiceState(owner, "running", pid, log_path, pid_path, state_path)
    return ChannelServiceState(owner, "stale", pid, log_path, pid_path, state_path)


def validate_active_channel_enabled(config) -> str:
    """校验当前是否启用了唯一 channel。"""
    kind = get_active_channel_kind(config)
    if not kind:
        raise typer.BadParameter("当前未启用任何 channel。\n请先运行：nomi channel enable weixin")
    get_channel_spec(kind)
    return kind
