"""定义 Nomi runtime 的共享状态。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from nomi.agent.loop import AgentLoop
from nomi.bus.queue import MessageBus
from nomi.config.schema import Config
from nomi.providers.base import LLMProvider
from nomi.providers.capabilities.transcription import QwenAsrTranscriptionProvider


@dataclass(slots=True)
class RuntimeState:
    """保存一份进程内 runtime 的核心依赖和运行状态。

    参数:
        config: 当前 runtime 使用的完整配置对象。
        bus: 主链路消息总线。
        provider: 已完成装配的 LLM 提供方。
        agent_loop: 复用主链路逻辑的执行循环。
        transcription_provider: 统一语音转写 provider。
        serve_task: 后台运行 `agent_loop.run()` 时持有的任务句柄。
        started: runtime 是否已经进入运行态。

    返回:
        无返回值。
    """

    config: Config
    bus: MessageBus
    provider: LLMProvider
    agent_loop: AgentLoop
    provider_builder: Callable[[Config], LLMProvider]
    agent_loop_factory: Callable[..., AgentLoop]
    transcription_provider: QwenAsrTranscriptionProvider | None = None
    serve_task: asyncio.Task[None] | None = None
    started: bool = False
