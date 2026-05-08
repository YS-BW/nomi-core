"""远程 desktop shell 服务配置。"""

from __future__ import annotations

from .base import StrictBase


class RemoteConfig(StrictBase):
    """远程 shell 服务配置。"""

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    auth_token: str = ""
