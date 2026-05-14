"""Provider 相关配置模型。"""

from __future__ import annotations

from pydantic import Field

from .base import Base


class ProviderConfig(Base):
    """单个 LLM provider 配置。"""

    api_key: str = ""
    api_base: str | None = None
    model: str | None = None
    extra_headers: dict[str, str] | None = None


class MimoProviderConfig(ProviderConfig):
    """MiMo provider 配置，额外支持 Token Plan 专用凭证。"""

    token_plan_api_key: str = ""
    token_plan_api_base: str | None = None


class ProvidersConfig(Base):
    """LLM providers 配置集合。"""

    custom: ProviderConfig = Field(default_factory=ProviderConfig)
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    minimax: ProviderConfig = Field(default_factory=ProviderConfig)
    qwen: ProviderConfig = Field(default_factory=ProviderConfig)
    mimo: MimoProviderConfig = Field(default_factory=MimoProviderConfig)
    azure_openai: ProviderConfig = Field(default_factory=ProviderConfig)
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    ollama: ProviderConfig = Field(default_factory=ProviderConfig)
    ovms: ProviderConfig = Field(default_factory=ProviderConfig)
    moonshot: ProviderConfig = Field(default_factory=ProviderConfig)
    aihubmix: ProviderConfig = Field(default_factory=ProviderConfig)
    siliconflow: ProviderConfig = Field(default_factory=ProviderConfig)
    volcengine: ProviderConfig = Field(default_factory=ProviderConfig)
    volcengine_coding_plan: ProviderConfig = Field(default_factory=ProviderConfig)
    byteplus: ProviderConfig = Field(default_factory=ProviderConfig)
    byteplus_coding_plan: ProviderConfig = Field(default_factory=ProviderConfig)
