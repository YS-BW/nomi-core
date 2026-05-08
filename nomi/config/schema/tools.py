"""工具系统相关配置模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import Base


class WebSearchConfig(Base):
    """Web 搜索工具配置。"""

    provider: str = "duckduckgo"
    api_key: str = ""
    base_url: str = ""
    max_results: int = 5
    timeout: int = 30


class WebToolsConfig(Base):
    """Web 工具配置。"""

    enable: bool = True
    proxy: str | None = None
    search: WebSearchConfig = Field(default_factory=WebSearchConfig)


class ExecToolConfig(Base):
    """Shell 执行工具配置。"""

    enable: bool = True
    timeout: int = 60
    path_append: str = ""
    sandbox: str = ""
    allowed_env_keys: list[str] = Field(default_factory=list)


class MCPServerConfig(Base):
    """MCP 服务连接配置。"""

    enabled: bool = True
    type: Literal["stdio", "sse", "streamableHttp"] | None = None
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    tool_timeout: int = 30
    enabled_tools: list[str] = Field(default_factory=lambda: ["*"])


class ToolsConfig(Base):
    """工具系统配置。"""

    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    restrict_to_workspace: bool = False
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)
