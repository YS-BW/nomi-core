"""AgentLoop 的内部运行态容器。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SessionInterruptState:
    """描述一个会话当前挂起的中断请求。"""

    reason: str
    requested_at: float
    handled: bool = False


@dataclass(slots=True)
class LoopRuntimeState:
    """聚合 AgentLoop 的运行中状态。"""

    start_time: float = field(default_factory=time.time)
    last_usage: dict[str, int] = field(default_factory=dict)
    running: bool = False
    mcp_connected: bool = False
    mcp_connecting: bool = False
    mcp_stacks: dict[str, Any] = field(default_factory=dict)
    active_tasks: dict[str, list[asyncio.Task]] = field(default_factory=dict)
    interrupt_requests: dict[str, SessionInterruptState] = field(default_factory=dict)
    background_tasks: list[asyncio.Task] = field(default_factory=list)
    session_locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    pending_queues: dict[str, asyncio.Queue] = field(default_factory=dict)
