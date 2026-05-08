"""AgentLoop 的内部支撑组件。"""

from __future__ import annotations

import asyncio
import dataclasses
from contextlib import nullcontext
from typing import TYPE_CHECKING

from loguru import logger

from nomi.bus.events import InboundMessage, OutboundMessage
from nomi.runtime.models import InterruptResult

from .state import LoopRuntimeState, SessionInterruptState

if TYPE_CHECKING:
    from nomi.agent.loop import AgentLoop
    from nomi.runtime.models import InterruptReason


class LoopControl:
    """管理 AgentLoop 的并发、中断和后台任务状态。"""

    def __init__(self, loop: "AgentLoop", state: LoopRuntimeState) -> None:
        """绑定主循环及共享运行时状态。

        参数:
            loop: 当前主循环 owner。
            state: 共享运行态容器。

        返回:
            无返回值。
        """
        self._loop = loop
        self._state = state

    @property
    def active_tasks(self) -> dict[str, list[asyncio.Task]]:
        """返回按会话聚合的活跃任务表。"""
        return self._state.active_tasks

    @property
    def interrupt_requests(self) -> dict[str, SessionInterruptState]:
        """返回挂起中的中断请求表。"""
        return self._state.interrupt_requests

    @property
    def pending_queues(self) -> dict[str, asyncio.Queue]:
        """返回待注入消息队列表。"""
        return self._state.pending_queues

    @property
    def session_locks(self) -> dict[str, asyncio.Lock]:
        """返回会话级串行锁表。"""
        return self._state.session_locks

    @property
    def background_tasks(self) -> list[asyncio.Task]:
        """返回当前登记中的后台任务列表。"""
        return self._state.background_tasks

    def stop(self) -> None:
        """停止消费新消息。"""
        self._state.running = False
        logger.info("Agent loop stopping")

    def is_running(self) -> bool:
        """返回当前是否处于运行状态。"""
        return self._state.running

    def mark_running(self, value: bool) -> None:
        """更新运行标记。"""
        self._state.running = value

    def get_lock(self, session_key: str) -> asyncio.Lock:
        """返回指定会话锁。"""
        return self._state.session_locks.setdefault(session_key, asyncio.Lock())

    def gate_context(self):
        """返回当前并发 gate 上下文。"""
        return self._loop._concurrency_gate or nullcontext()

    async def cancel_session_tasks(self, session_key: str) -> int:
        """取消指定会话下的活跃任务。"""
        session_key = self._loop._normalize_control_session_key(session_key)
        tasks = self._state.active_tasks.pop(session_key, [])
        cancelled = sum(1 for task in tasks if not task.done() and task.cancel())
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        return cancelled

    def interrupt_session(
        self,
        session_key: str,
        reason: "InterruptReason" = "user_interrupt",
    ) -> InterruptResult:
        """向指定会话发出一次显式中断请求。"""
        session_key = self._loop._normalize_control_session_key(session_key)
        current = self._state.interrupt_requests.get(session_key)
        if current is not None and not current.handled:
            return InterruptResult(
                session_id=session_key,
                reason=current.reason,
                accepted=False,
                cancelled_tasks=0,
                already_interrupting=True,
            )

        active_tasks = [task for task in self._state.active_tasks.get(session_key, []) if not task.done()]
        if not active_tasks:
            return InterruptResult(
                session_id=session_key,
                reason=reason,
                accepted=False,
                cancelled_tasks=0,
                already_interrupting=False,
            )

        self._state.interrupt_requests[session_key] = SessionInterruptState(
            reason=reason,
            requested_at=self._loop._now(),
        )
        cancelled = 0
        for task in active_tasks:
            if task.cancel():
                cancelled += 1
        return InterruptResult(
            session_id=session_key,
            reason=reason,
            accepted=cancelled > 0,
            cancelled_tasks=cancelled,
            already_interrupting=False,
        )

    def peek_interrupt_state(self, session_key: str) -> SessionInterruptState | None:
        """读取挂起中断请求。"""
        state = self._state.interrupt_requests.get(session_key)
        if state is None or state.handled:
            return None
        return state

    def consume_interrupt_state(self, session_key: str) -> SessionInterruptState | None:
        """消费并清理挂起中断请求。"""
        state = self._state.interrupt_requests.pop(session_key, None)
        if state is None:
            return None
        state.handled = True
        return state

    def clear_interrupt_state(self, session_key: str) -> None:
        """清理挂起中断请求。"""
        self._state.interrupt_requests.pop(session_key, None)

    def register_active_task(self, session_key: str, task: asyncio.Task) -> None:
        """登记会话活跃任务。"""
        self._state.active_tasks.setdefault(session_key, []).append(task)

        def _cleanup(done_task: asyncio.Task, *, key: str = session_key) -> None:
            tasks = self._state.active_tasks.get(key, [])
            if done_task in tasks:
                tasks.remove(done_task)
            if not tasks:
                self._state.active_tasks.pop(key, None)

        task.add_done_callback(_cleanup)

    def create_pending_queue(self, session_key: str, maxsize: int = 20) -> asyncio.Queue:
        """创建并登记待注入队列。"""
        pending = asyncio.Queue(maxsize=maxsize)
        self._state.pending_queues[session_key] = pending
        return pending

    async def cleanup_pending_queue(self, session_key: str) -> None:
        """清理并回灌残留待注入消息。"""
        queue = self._state.pending_queues.pop(session_key, None)
        if queue is None:
            return
        leftover = 0
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            await self._loop.bus.publish_inbound(item)
            leftover += 1
        if leftover:
            logger.info(
                "Re-published {} leftover message(s) to bus for session {}",
                leftover,
                session_key,
            )

    def drop_pending_queue(self, session_key: str) -> int:
        """直接丢弃指定会话的待注入消息队列。"""
        queue = self._state.pending_queues.pop(session_key, None)
        if queue is None:
            return 0
        dropped = 0
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            dropped += 1
        if dropped:
            logger.info("Dropped {} pending message(s) for session {}", dropped, session_key)
        return dropped

    def route_followup_to_pending(self, msg: InboundMessage) -> bool:
        """尝试把追问路由到当前会话待注入队列。"""
        effective_key = self._loop._effective_session_key(msg)
        if effective_key not in self._state.pending_queues:
            return False
        pending_msg = msg
        if effective_key != msg.session_key:
            pending_msg = dataclasses.replace(msg, session_key_override=effective_key)
        try:
            self._state.pending_queues[effective_key].put_nowait(pending_msg)
        except asyncio.QueueFull:
            logger.warning(
                "Pending queue full for session {}, falling back to queued task",
                effective_key,
            )
            return False
        logger.info("Routed follow-up message to pending queue for session {}", effective_key)
        return True

    def schedule_background(self, coro) -> None:
        """注册后台协程，并在结束后自动移除。"""
        task = asyncio.create_task(coro)
        self._state.background_tasks.append(task)

        def _cleanup(done_task: asyncio.Task) -> None:
            if done_task in self._state.background_tasks:
                self._state.background_tasks.remove(done_task)

        task.add_done_callback(_cleanup)

    async def close_background(self) -> None:
        """等待所有后台任务结束。"""
        if self._state.background_tasks:
            await asyncio.gather(*self._state.background_tasks, return_exceptions=True)
            self._state.background_tasks.clear()


class LoopMcpSupport:
    """管理 AgentLoop 的 MCP 生命周期。"""

    def __init__(self, loop: "AgentLoop", state: LoopRuntimeState) -> None:
        """绑定主循环及共享运行态。

        参数:
            loop: 当前主循环 owner。
            state: 共享运行态容器。

        返回:
            无返回值。
        """
        self._loop = loop
        self._state = state

    @property
    def mcp_connected(self) -> bool:
        """返回 MCP 是否已完成连接。"""
        return self._state.mcp_connected

    @property
    def mcp_stacks(self) -> dict[str, object]:
        """返回当前各 MCP server 的连接栈。"""
        return self._state.mcp_stacks

    async def connect(self) -> None:
        """按需连接 MCP servers。"""
        if self._state.mcp_connected or self._state.mcp_connecting or not self._loop._mcp_servers:
            return
        self._state.mcp_connecting = True
        from nomi.agent.tools.mcp import connect_mcp_servers

        try:
            enabled_servers = {
                name: config
                for name, config in self._loop._mcp_servers.items()
                if getattr(config, "enabled", True)
            }
            if not enabled_servers:
                self._state.mcp_connected = False
                self._state.mcp_stacks.clear()
                return
            self._state.mcp_stacks = await connect_mcp_servers(
                enabled_servers,
                self._loop.tools,
            )
            if self._state.mcp_stacks:
                self._state.mcp_connected = True
            else:
                logger.warning("No MCP servers connected successfully (will retry next message)")
        except asyncio.CancelledError:
            logger.warning("MCP connection cancelled (will retry next message)")
            self._state.mcp_stacks.clear()
            self._state.mcp_connected = False
        except BaseException as exc:
            logger.error("Failed to connect MCP servers (will retry next message): {}", exc)
            self._state.mcp_stacks.clear()
            self._state.mcp_connected = False
        finally:
            self._state.mcp_connecting = False

    async def close(self) -> None:
        """关闭已连接的 MCP stacks。"""
        for name, stack in self._state.mcp_stacks.items():
            try:
                await stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                logger.debug("MCP server '{}' cleanup error (can be ignored)", name)
        self._state.mcp_stacks.clear()
        self._state.mcp_connected = False
        for tool_name in list(self._loop.tools.tool_names):
            if tool_name.startswith("mcp_"):
                self._loop.tools.unregister(tool_name)
