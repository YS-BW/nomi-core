"""status 与 instance services 的状态聚合。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nomi.channel.registry import channel_has_login_state, get_active_channel_kind
from nomi.config.instance import (
    DEFAULT_INSTANCE_NAME,
    format_instance_name,
    instance_context_scope,
    list_instance_contexts,
)
from nomi.config.loader import get_config_path, load_config, resolve_config_env_vars
from nomi.runtime.service.state import build_runtime_status_snapshot
from nomi.tasks.runner import TaskRunner


@dataclass(frozen=True, slots=True)
class StatusRow:
    """单行状态展示。"""

    key: str
    value: str
    description: str


def format_home_path(path: Path) -> str:
    """把家目录下的绝对路径压缩成 `~` 开头。"""
    try:
        return str(path).replace(str(Path.home()), "~", 1)
    except Exception:
        return str(path)


def build_status_rows(
    *,
    config: str | None = None,
    instance: str | None = None,
    instance_root: str | None = None,
) -> list[StatusRow]:
    """构造 status 命令展示数据。"""
    with instance_context_scope(instance=instance, instance_root=instance_root, config_path=config):
        config_path = get_config_path()
        loaded = resolve_config_env_vars(load_config(config_path))
        workspace = loaded.workspace_path
        runtime_snapshot = build_runtime_status_snapshot(loaded)
        scheduler_info = TaskRunner.__new__(TaskRunner).read_scheduler_owner_info()
        scheduler_owner = scheduler_info.get("owner", "-")
        scheduler_active = "yes" if scheduler_info or runtime_snapshot.running else "no"
        instance_label = format_instance_name(instance or DEFAULT_INSTANCE_NAME)
        return [
            StatusRow("Instance", instance_label, "当前命令绑定的实例名"),
            StatusRow("Config", format_home_path(config_path), "当前加载的配置文件路径"),
            StatusRow(
                "Workspace",
                format_home_path(workspace) if workspace.exists() else "不存在",
                "当前工作区目录状态",
            ),
            StatusRow("Provider", loaded.agents.defaults.provider, "当前默认模型提供方"),
            StatusRow("Model", loaded.agents.defaults.model, "当前默认对话模型"),
            StatusRow("Timezone", loaded.agents.defaults.timezone, "agent 默认使用的时区"),
            StatusRow(
                "Runtime Running",
                "yes" if runtime_snapshot.running else "no",
                "当前实例唯一 runtime 是否运行",
            ),
            StatusRow(
                "Runtime PID",
                str(runtime_snapshot.pid or "-"),
                "当前实例唯一 runtime 进程 ID",
            ),
            StatusRow(
                "Runtime Log",
                format_home_path(runtime_snapshot.log_path),
                "统一 runtime 日志文件路径",
            ),
            StatusRow("Task Scheduler Owner", scheduler_owner, "当前实例 task scheduler owner"),
            StatusRow("Task Scheduler Active", scheduler_active, "当前是否已有 task scheduler owner"),
            StatusRow(
                "Channel Enabled",
                "yes" if runtime_snapshot.channel_enabled else "no",
                "是否启用了外部 channel 入口",
            ),
            StatusRow(
                "Channel Owner",
                runtime_snapshot.channel_kind or "-",
                "当前唯一 channel 的实现 owner",
            ),
            StatusRow(
                "Channel Running",
                "yes" if runtime_snapshot.channel_running else "no",
                "当前 runtime 是否已挂载 channel adapter",
            ),
            StatusRow(
                "Channel Logged In",
                "yes" if runtime_snapshot.channel_logged_in else "no",
                "当前是否已有可用登录态",
            ),
            StatusRow(
                "Channel Uptime",
                runtime_snapshot.uptime_text,
                "当前统一 runtime 运行时长；未运行时为空",
            ),
            StatusRow(
                "Remote Enabled",
                "yes" if runtime_snapshot.remote_enabled else "no",
                "是否启用了 remote 服务",
            ),
            StatusRow(
                "Remote Running",
                "yes" if runtime_snapshot.remote_running else "no",
                "当前 runtime 是否已挂载 remote adapter",
            ),
            StatusRow("Remote Host", runtime_snapshot.remote_host, "remote 监听地址"),
            StatusRow("Remote Port", str(runtime_snapshot.remote_port), "remote 监听端口"),
        ]


def build_instance_service_rows() -> list[dict[str, str]]:
    """汇总所有实例的服务状态。"""
    rows: list[dict[str, str]] = []
    for context in list_instance_contexts():
        with instance_context_scope(context=context):
            config = resolve_config_env_vars(load_config(get_config_path()))
            runtime_snapshot = build_runtime_status_snapshot(config)
            scheduler_info = TaskRunner.__new__(TaskRunner).read_scheduler_owner_info()
            channel_kind = get_active_channel_kind(config)
            logged_in = channel_has_login_state(config, channel_kind) if channel_kind else False
            rows.append(
                {
                    "instance": format_instance_name(context.name),
                    "root": format_home_path(context.root),
                    "scheduler": scheduler_info.get("owner", runtime_snapshot.scheduler_owner),
                    "runtime": (
                        f"{runtime_snapshot.service_state}"
                        + (f" pid={runtime_snapshot.pid}" if runtime_snapshot.pid else "")
                    ),
                    "remote": (
                        "running" if runtime_snapshot.remote_running else (
                            "enabled" if runtime_snapshot.remote_enabled else "disabled"
                        )
                    ),
                    "channel": (
                        "running" if runtime_snapshot.channel_running else (
                            "enabled" if runtime_snapshot.channel_enabled else "disabled"
                        )
                    ),
                    "port": str(config.remote.port),
                    "login": "yes" if logged_in else "no",
                    "logs": (
                        f"runtime={format_home_path(runtime_snapshot.log_path)}"
                    ),
                }
            )
    return rows
