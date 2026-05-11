"""status 与 instance services 的状态聚合。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nomi.channel.registry import channel_has_login_state, get_active_channel_kind
from nomi.channel.service.state import build_channel_status_snapshot
from nomi.config.instance import (
    DEFAULT_INSTANCE_NAME,
    format_instance_name,
    instance_context_scope,
    list_instance_contexts,
)
from nomi.config.loader import get_config_path, load_config, resolve_config_env_vars
from nomi.remote.service.state import build_remote_status_snapshot


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
        channel_snapshot = build_channel_status_snapshot(loaded)
        remote_snapshot = build_remote_status_snapshot(loaded)
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
                "Channel Enabled",
                "yes" if channel_snapshot.enabled else "no",
                "是否启用了外部 channel 入口",
            ),
            StatusRow(
                "Channel Owner",
                channel_snapshot.owner or "-",
                "当前唯一 channel 的实现 owner",
            ),
            StatusRow(
                "Channel Running",
                "yes" if channel_snapshot.running else "no",
                "当前是否有 channel 服务正在运行",
            ),
            StatusRow(
                "Channel Logged In",
                "yes" if channel_snapshot.logged_in else "no",
                "当前是否已有可用登录态",
            ),
            StatusRow(
                "Channel Uptime",
                channel_snapshot.uptime_text,
                "当前运行时长；未运行时为空",
            ),
            StatusRow(
                "Channel Log",
                format_home_path(channel_snapshot.log_path),
                "后台服务日志文件路径",
            ),
            StatusRow(
                "Remote Enabled",
                "yes" if remote_snapshot.enabled else "no",
                "是否启用了 remote 服务",
            ),
            StatusRow(
                "Remote Running",
                "yes" if remote_snapshot.running else "no",
                "当前 remote 服务是否正在运行",
            ),
            StatusRow("Remote Host", remote_snapshot.host, "remote 监听地址"),
            StatusRow("Remote Port", str(remote_snapshot.port), "remote 监听端口"),
            StatusRow(
                "Remote Uptime",
                remote_snapshot.uptime_text,
                "remote 服务运行时长；未运行时为空",
            ),
            StatusRow(
                "Remote Log",
                format_home_path(remote_snapshot.log_path),
                "remote 服务日志文件路径",
            ),
        ]


def build_instance_service_rows() -> list[dict[str, str]]:
    """汇总所有实例的服务状态。"""
    rows: list[dict[str, str]] = []
    for context in list_instance_contexts():
        with instance_context_scope(context=context):
            config = resolve_config_env_vars(load_config(get_config_path()))
            channel_snapshot = build_channel_status_snapshot(config)
            remote_snapshot = build_remote_status_snapshot(config)
            channel_kind = get_active_channel_kind(config)
            logged_in = channel_has_login_state(config, channel_kind) if channel_kind else False
            rows.append(
                {
                    "instance": format_instance_name(context.name),
                    "root": format_home_path(context.root),
                    "channel": (
                        f"{channel_snapshot.service_state}"
                        + (f" pid={channel_snapshot.pid}" if channel_snapshot.pid else "")
                    ),
                    "remote": (
                        f"{remote_snapshot.service_state}"
                        + (f" pid={remote_snapshot.pid}" if remote_snapshot.pid else "")
                    ),
                    "port": str(config.remote.port),
                    "login": "yes" if logged_in else "no",
                    "logs": (
                        f"channel={format_home_path(channel_snapshot.log_path)} "
                        f"remote={format_home_path(remote_snapshot.log_path)}"
                    ),
                }
            )
    return rows
