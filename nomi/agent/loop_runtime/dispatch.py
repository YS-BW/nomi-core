"""AgentLoop 入站分发与并发 gate owner。"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from contextlib import nullcontext
from typing import TYPE_CHECKING, Awaitable, Callable

from loguru import logger

from nomi.bus.events import InboundMessage, OutboundMessage

if TYPE_CHECKING:
    from nomi.agent.loop import AgentLoop
    from nomi.agent.execution.processor import DirectProcessResult


class DispatchRuntime:
    """负责 bus 消费、会话串行化与 direct dispatch。"""

    def __init__(self, loop: "AgentLoop") -> None:
        """绑定所属主循环。

        参数:
            loop: 当前主循环 owner。

        返回:
            无返回值。
        """
        self._loop = loop

    async def run(self) -> None:
        """持续消费消息总线并分发任务。"""
        loop = self._loop
        loop._control.mark_running(True)
        await loop._connect_mcp()
        loop.tasks.start_scheduler()
        logger.info("Agent loop started")

        while loop._control.is_running():
            try:
                msg = await asyncio.wait_for(loop.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                loop.tasks.poll_scheduler()
                await loop.poll_global_reminders()
                loop.auto_compact.check_expired(loop._schedule_background)
                continue
            except asyncio.CancelledError:
                if not loop._state.running or asyncio.current_task().cancelling():
                    raise
                continue
            except Exception as exc:
                logger.warning("Error consuming inbound message: {}, continuing...", exc)
                continue

            raw = msg.content.strip()
            if loop.commands.is_priority(raw):
                ctx = loop._build_command_context(msg=msg, session=None, key=msg.session_key, raw=raw)
                result = await loop.commands.dispatch_priority(ctx)
                if result:
                    await loop.bus.publish_outbound(result)
                continue

            effective_key = loop._effective_session_key(msg)
            if loop._control.route_followup_to_pending(msg):
                continue

            task = asyncio.create_task(loop._dispatch(msg))
            loop._control.register_active_task(effective_key, task)

    async def dispatch(self, msg: InboundMessage) -> None:
        """处理一条入站消息。"""
        loop = self._loop
        session_key = loop._effective_session_key(msg)
        if session_key != msg.session_key:
            msg = dataclasses.replace(msg, session_key_override=session_key)
        lock = loop._control.get_lock(session_key)
        gate = loop._control.gate_context()
        pending = loop._control.create_pending_queue(session_key)

        try:
            async with lock, gate:
                try:
                    on_stream = on_stream_end = None
                    if msg.metadata.get("_wants_stream"):
                        on_stream, on_stream_end = self._build_stream_callbacks(msg)

                    response = await loop._process_message(
                        msg,
                        on_stream=on_stream,
                        on_stream_end=on_stream_end,
                        pending_queue=pending,
                    )
                    if response is not None:
                        await loop.bus.publish_outbound(response)
                    elif msg.channel == "cli":
                        await loop.bus.publish_outbound(
                            OutboundMessage(
                                channel=msg.channel,
                                chat_id=msg.chat_id,
                                content="",
                                metadata=msg.metadata or {},
                            )
                        )
                except asyncio.CancelledError:
                    interrupt_state = loop._consume_interrupt_state(session_key)
                    if interrupt_state is None:
                        logger.info("Task cancelled for session {}", session_key)
                        raise
                    logger.info(
                        "Task interrupted for session {} with reason {}",
                        session_key,
                        interrupt_state.reason,
                    )
                    session = loop.sessions.get_or_create(session_key)
                    loop._finalize_interrupted_turn(session, interrupt_state.reason)
                    await loop.bus.publish_outbound(
                        loop._build_interrupted_outbound(msg, interrupt_state.reason)
                    )
                except Exception:
                    logger.exception("Error processing message for session {}", session_key)
                    await loop.bus.publish_outbound(
                        OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content="Sorry, I encountered an error.",
                            metadata=dict(msg.metadata or {}),
                        )
                    )
        finally:
            await loop._control.cleanup_pending_queue(session_key)

    async def process_direct_result(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        history_session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        persist_session: bool = True,
    ) -> "DirectProcessResult":
        """直接处理一条消息，并返回完整执行结果。"""
        loop = self._loop
        await loop._connect_mcp()
        normalized_key = loop._normalize_control_session_key(session_key)
        msg = InboundMessage(
            channel=channel,
            sender_id="user",
            chat_id=chat_id,
            content=content,
            session_key_override=normalized_key,
        )
        lock = loop._control.get_lock(normalized_key)
        gate = loop._concurrency_gate or nullcontext()
        current_task = asyncio.current_task()
        if current_task is not None:
            loop._control.register_active_task(normalized_key, current_task)
        try:
            async with lock, gate:
                try:
                    return await loop._process_message_result(
                        msg,
                        session_key=normalized_key,
                        history_session_key=history_session_key,
                        on_progress=on_progress,
                        on_stream=on_stream,
                        on_stream_end=on_stream_end,
                        persist_session=persist_session,
                    )
                except asyncio.CancelledError:
                    interrupt_state = loop._consume_interrupt_state(normalized_key)
                    if interrupt_state is None:
                        raise
                    session = loop.sessions.get_or_create(normalized_key)
                    loop._finalize_interrupted_turn(session, interrupt_state.reason)
                    outbound = loop._build_interrupted_outbound(msg, interrupt_state.reason)
                    from nomi.agent.execution.processor import DirectProcessResult

                    return DirectProcessResult(
                        outbound=outbound,
                        final_content=outbound.content,
                        stop_reason="interrupted",
                        session_key=normalized_key,
                        interrupt_reason=interrupt_state.reason,
                    )
        finally:
            if current_task is not None:
                tasks = loop._state.active_tasks.get(normalized_key, [])
                if current_task in tasks:
                    tasks.remove(current_task)
                if not tasks:
                    loop._state.active_tasks.pop(normalized_key, None)

    def _build_stream_callbacks(
        self,
        msg: InboundMessage,
    ) -> tuple[
        Callable[[str], Awaitable[None]],
        Callable[..., Awaitable[None]],
    ]:
        """构造当前消息的流式转发回调。"""
        loop = self._loop
        stream_base_id = f"{msg.session_key}:{time.time_ns()}"
        stream_segment = 0

        def _current_stream_id() -> str:
            return f"{stream_base_id}:{stream_segment}"

        async def on_stream(delta: str) -> None:
            """转发一段流式正文增量。"""
            meta = dict(msg.metadata or {})
            meta["_stream_delta"] = True
            meta["_stream_id"] = _current_stream_id()
            await loop.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=delta,
                    metadata=meta,
                )
            )

        async def on_stream_end(*, resuming: bool = False) -> None:
            """转发当前一段流式输出的收尾事件。"""
            nonlocal stream_segment
            meta = dict(msg.metadata or {})
            meta["_stream_end"] = True
            meta["_resuming"] = resuming
            meta["_stream_id"] = _current_stream_id()
            await loop.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="",
                    metadata=meta,
                )
            )
            stream_segment += 1

        return on_stream, on_stream_end
