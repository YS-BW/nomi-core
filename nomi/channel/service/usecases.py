"""channel 子系统高层 usecase。"""

from __future__ import annotations

import asyncio

from nomi.channel.service.login import ChannelLoginRuntime
from nomi.channel.registry import build_active_channel
from nomi.channel.service.state import validate_active_channel_enabled


def login_active_channel(loaded_config, *, force: bool) -> bool:
    """执行当前启用 channel 的交互式登录。"""
    validate_active_channel_enabled(loaded_config)
    runtime = ChannelLoginRuntime(loaded_config)
    channel = build_active_channel(loaded_config, runtime)
    return asyncio.run(channel.login(force=force))
