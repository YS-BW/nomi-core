"""Agent 相关配置模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import Base


class DreamConfig(Base):
    """Dream 记忆整理配置。"""

    model_override: str | None = None
    max_batch_size: int = Field(default=20, ge=1)
    max_iterations: int = Field(default=10, ge=1)


class AgentDefaults(Base):
    """Agent 默认配置。"""

    workspace: str = "~/.nomi/workspace"
    model: str = "mimo-v2.5"
    provider: str = "mimo"
    max_tokens: int = 8192
    context_window_tokens: int = 65_536
    context_block_limit: int | None = None
    temperature: float = 0.1
    max_tool_iterations: int = 200
    max_tool_result_chars: int = 16_000
    provider_retry_mode: Literal["standard", "persistent"] = "standard"
    reasoning_effort: str | None = None
    timezone: str = "Asia/Shanghai"
    task_execution_timeout_seconds: int = Field(default=180, ge=1)
    unified_session: bool = False
    idle_compact_after_minutes: int = Field(default=0, ge=0)
    dream: DreamConfig = Field(default_factory=DreamConfig)


class AgentsConfig(Base):
    """Agent 配置。"""

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)
