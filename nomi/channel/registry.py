"""外部 channel 注册表。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nomi.channel.base import BaseChannel
from nomi.channel.adapters.weixin.channel import WeixinChannel
from nomi.config.paths import get_runtime_subdir
from nomi.config.schema import Config


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    """描述一种可被激活的 channel。"""

    kind: str
    adapter_class: type[BaseChannel]
    state_filename: str


_CHANNEL_SPECS: dict[str, ChannelSpec] = {
    "weixin": ChannelSpec(
        kind="weixin",
        adapter_class=WeixinChannel,
        state_filename="account.json",
    ),
}


def get_active_channel_kind(config: Config) -> str:
    """返回当前启用的唯一 channel kind。"""
    return str(config.channel.kind or "").strip()


def get_active_channel_spec(config: Config) -> ChannelSpec:
    """返回当前启用 channel 的规格。"""
    kind = get_active_channel_kind(config)
    if not kind:
        raise ValueError("当前未启用任何 channel。请先在配置中设置 `channel.kind`。")
    try:
        return _CHANNEL_SPECS[kind]
    except KeyError as exc:
        raise ValueError(f"当前 channel.kind 不受支持: {kind}") from exc


def get_channel_spec(kind: str) -> ChannelSpec:
    """按 kind 返回 channel 规格。"""
    try:
        return _CHANNEL_SPECS[kind]
    except KeyError as exc:
        raise ValueError(f"当前 channel.kind 不受支持: {kind}") from exc


def get_channel_config(config: Config, kind: str | None = None) -> Any:
    """返回指定 kind 的平台配置对象。"""
    resolved_kind = kind or get_active_channel_kind(config)
    if not resolved_kind:
        raise ValueError("当前未启用任何 channel。请先在配置中设置 `channel.kind`。")
    try:
        return getattr(config.channel, resolved_kind)
    except AttributeError as exc:
        raise ValueError(f"找不到 channel 配置段: {resolved_kind}") from exc


def get_active_channel_config(config: Config) -> Any:
    """返回当前启用 channel 的配置对象。"""
    return get_channel_config(config, get_active_channel_kind(config))


def build_active_channel(config: Config, runtime: Any) -> BaseChannel:
    """构造当前启用的 channel 实例。"""
    spec = get_active_channel_spec(config)
    channel_config = get_active_channel_config(config)
    return spec.adapter_class(channel_config, runtime)


def get_channel_state_path(config: Config, kind: str | None = None) -> Path:
    """返回当前 channel 的登录态文件路径。"""
    resolved_kind = kind or get_active_channel_kind(config)
    spec = get_channel_spec(resolved_kind)
    channel_config = get_channel_config(config, resolved_kind)
    state_dir = str(getattr(channel_config, "state_dir", "") or "").strip()
    if state_dir:
        base_dir = Path(state_dir).expanduser()
    else:
        base_dir = get_runtime_subdir(resolved_kind)
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / spec.state_filename


def channel_has_login_state(config: Config, kind: str | None = None) -> bool:
    """判断当前 channel 是否已有可用登录态。"""
    resolved_kind = kind or get_active_channel_kind(config)
    channel_config = get_channel_config(config, resolved_kind)
    token = str(getattr(channel_config, "token", "") or "").strip()
    return bool(token) or get_channel_state_path(config, resolved_kind).is_file()
