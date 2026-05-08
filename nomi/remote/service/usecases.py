"""remote 子系统高层 usecase。"""

from __future__ import annotations

from nomi.channel.service.runner import follow_log_file
from nomi.remote.service.runner import (
    restart_background_service,
    run_foreground_service,
    start_background_service,
    stop_background_service,
)
from nomi.remote.service.state import get_service_log_path, get_service_state


def run_remote_service_foreground(loaded_config, runtime_factory) -> None:
    """以前台方式运行 remote service。"""
    run_foreground_service(loaded_config, runtime_factory)


def serve_remote_internal(loaded_config, runtime_factory) -> None:
    """后台 service 内部入口。"""
    run_foreground_service(loaded_config, runtime_factory)


def start_remote_service(config_arg: str | None, workspace: str | None, loaded_config) -> None:
    """后台启动 remote service。"""
    start_background_service(config_arg, workspace, loaded_config)


def stop_remote_service(config=None) -> None:
    """停止后台 remote service。"""
    stop_background_service(config)


def restart_remote_service(config_arg: str | None, workspace: str | None, loaded_config) -> None:
    """重启后台 remote service。"""
    restart_background_service(config_arg, workspace, loaded_config)


def tail_remote_service_log() -> None:
    """实时输出后台日志。"""
    follow_log_file(get_service_log_path())


def get_remote_service_state(config=None):
    """返回当前 remote service 状态。"""
    return get_service_state(config)
