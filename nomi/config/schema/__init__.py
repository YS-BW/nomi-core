"""配置 schema 对外导出。"""

from .agent import AgentDefaults, AgentsConfig, DreamConfig
from .channel import ChannelConfig, FeishuChannelConfig, WeixinChannelConfig
from .provider import CustomProviderConfig, MimoProviderConfig, ProviderConfig, ProvidersConfig
from .remote import RemoteConfig
from .root import Config
from .skills import SkillsConfig
from .tools import ExecToolConfig, MCPServerConfig, ToolsConfig, WebSearchConfig, WebToolsConfig
from .transcription import TranscriptionConfig

__all__ = [
    "AgentDefaults",
    "AgentsConfig",
    "ChannelConfig",
    "Config",
    "CustomProviderConfig",
    "DreamConfig",
    "ExecToolConfig",
    "FeishuChannelConfig",
    "MCPServerConfig",
    "MimoProviderConfig",
    "ProviderConfig",
    "ProvidersConfig",
    "RemoteConfig",
    "SkillsConfig",
    "ToolsConfig",
    "TranscriptionConfig",
    "WebSearchConfig",
    "WebToolsConfig",
    "WeixinChannelConfig",
]
