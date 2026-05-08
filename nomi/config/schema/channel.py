"""外部 channel 配置模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import StrictBase


class WeixinChannelConfig(StrictBase):
    """个人微信 channel 配置。"""

    allow_from: list[str] = Field(default_factory=lambda: ["*"])
    base_url: str = "https://ilinkai.weixin.qq.com"
    route_tag: str | int | None = None
    token: str = ""
    state_dir: str = ""
    poll_timeout: int = Field(default=35, ge=1)


class FeishuChannelConfig(StrictBase):
    """飞书 channel 预留配置壳。"""

    app_id: str = ""
    app_secret: str = ""
    state_dir: str = ""


class ChannelConfig(StrictBase):
    """单入口外部 channel 配置。"""

    kind: Literal["", "weixin", "feishu"] = ""
    weixin: WeixinChannelConfig = Field(default_factory=WeixinChannelConfig)
    feishu: FeishuChannelConfig = Field(default_factory=FeishuChannelConfig)
