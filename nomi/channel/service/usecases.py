"""channel 子系统高层 usecase。"""

from __future__ import annotations

import asyncio

from nomi.channel.service.login import ChannelLoginRuntime
from nomi.channel.registry import build_active_channel
from nomi.channel.service.state import validate_active_channel_enabled
from nomi.channel.service.runner import (
    follow_log_file,
    restart_background_service,
    run_active_channel_foreground,
    start_background_service,
    stop_background_service,
)
from nomi.channel.service.state import (
    cleanup_stale_pid_file,
    ensure_runtime_not_occupied,
    get_service_log_path,
    get_service_state,
    validate_active_channel_ready,
)


def login_active_channel(loaded_config, *, force: bool) -> bool:
    """执行当前启用 channel 的交互式登录。"""
    validate_active_channel_enabled(loaded_config)
    runtime = ChannelLoginRuntime(loaded_config)
    channel = build_active_channel(loaded_config, runtime)
    return asyncio.run(channel.login(force=force))


def run_channel_foreground(loaded_config, runtime_factory) -> None:
    """以前台方式运行 channel。"""
    ensure_runtime_not_occupied(loaded_config)
    validate_active_channel_ready(loaded_config)
    asyncio.run(run_active_channel_foreground(loaded_config, runtime_factory))


def serve_channel_internal(loaded_config, runtime_factory) -> None:
    """后台 service 内部入口，绕过外层互斥检查。"""
    validate_active_channel_ready(loaded_config)
    asyncio.run(run_active_channel_foreground(loaded_config, runtime_factory))


def start_channel_service(config_arg: str | None, workspace: str | None, loaded_config) -> None:
    """后台启动 channel service。"""
    start_background_service(config_arg, workspace, loaded_config)


def stop_channel_service(config=None) -> None:
    """停止后台 channel service。"""
    stop_background_service(config)


def restart_channel_service(config_arg: str | None, workspace: str | None, loaded_config) -> None:
    """重启后台 channel service。"""
    restart_background_service(config_arg, workspace, loaded_config)


def tail_channel_service_log() -> None:
    """实时输出后台日志。"""
    follow_log_file(get_service_log_path())


def get_channel_service_state(config=None):
    """返回当前 channel service 状态。"""
    return get_service_state(config)


def cleanup_channel_stale_pid(path) -> None:
    """清理失效 pid 文件。"""
    cleanup_stale_pid_file(path)
