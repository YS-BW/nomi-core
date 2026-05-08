"""根配置模型。"""

from __future__ import annotations

from pathlib import Path

from pydantic import ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings

from .agent import AgentsConfig
from .channel import ChannelConfig
from .provider import ProvidersConfig
from .remote import RemoteConfig
from .tools import ToolsConfig
from .transcription import TranscriptionConfig


class Config(BaseSettings):
    """nomi 根配置。"""

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    transcription: TranscriptionConfig = Field(default_factory=TranscriptionConfig)
    channel: ChannelConfig = Field(default_factory=ChannelConfig)
    remote: RemoteConfig = Field(default_factory=RemoteConfig)

    @property
    def workspace_path(self) -> Path:
        """返回展开后的工作区路径。"""
        return Path(self.agents.defaults.workspace).expanduser()

    model_config = ConfigDict(
        env_prefix="NOMI_",
        env_nested_delimiter="__",
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )
