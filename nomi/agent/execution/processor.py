"""AgentLoop 单轮执行 owner。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nomi.agent.context.runtime_blocks import (
    RUNTIME_CONTEXT_END,
    RUNTIME_CONTEXT_TAG,
    build_runtime_context,
    build_user_content,
)
from nomi.agent.execution.messages import build_assistant_message
from nomi.agent.execution.runner import _MAX_INJECTIONS_PER_TURN, AgentRunSpec
from nomi.agent.execution.turn_journal import (
    ToolJournalEntry,
    TurnJournalRecord,
    attach_running_journal_metadata,
    clear_running_journal_metadata,
    consume_previous_interrupted_metadata,
    set_previous_interrupted_metadata,
)
from nomi.agent.hook import AgentHook, AgentHookContext, CompositeHook
from nomi.bus.events import InboundMessage, OutboundMessage
from nomi.runtime.models import InterruptReason
from nomi.session.manager import Session
from nomi.utils.runtime import EMPTY_FINAL_RESPONSE_MESSAGE
from nomi.utils.text import image_placeholder_text, strip_think
from nomi.utils.text import truncate_text as truncate_text_fn

if TYPE_CHECKING:
    import asyncio

    from nomi.agent.loop import AgentLoop


@dataclass(slots=True)
class DirectProcessResult:
    """一次直连调用的完整结果。"""

    outbound: OutboundMessage | None
    final_content: str | None = None
    tools_used: list[str] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = "completed"
    session_key: str = ""
    interrupt_reason: InterruptReason | None = None
    saw_stream_delta: bool = False


class _LoopHook(AgentHook):
    """把 Runner 生命周期事件桥接回主循环外层能力。"""

    def __init__(
        self,
        agent_loop: "AgentLoop",
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        *,
        channel: str = "cli",
        chat_id: str = "direct",
        message_id: str | None = None,
        session_key: str | None = None,
        turn_journal: TurnJournalRecord | None = None,
    ) -> None:
        """绑定单轮 hook 需要回写到外层的能力。

        参数:
            agent_loop: 当前所属的 AgentLoop。
            on_progress: 进度回调。
            on_stream: 流式正文回调。
            on_stream_end: 流式收尾回调。
            channel: 当前消息通道。
            chat_id: 当前会话标识。
            message_id: 当前消息标识。
            session_key: 当前统一会话键。

        返回:
            无返回值。
        """
        super().__init__(reraise=True)
        self._loop = agent_loop
        self._on_progress = on_progress
        self._on_stream = on_stream
        self._on_stream_end = on_stream_end
        self._channel = channel
        self._chat_id = chat_id
        self._message_id = message_id
        self._session_key = session_key
        self._turn_journal = turn_journal
        self._stream_buf = ""
        self._saw_stream_delta = False

    def wants_streaming(self) -> bool:
        """只有外层声明需要流式输出时，才要求 Runner 逐段回调。"""
        return self._on_stream is not None

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        """把本轮新增的可见正文片段转发给外层。"""
        del context
        prev_clean = strip_think(self._stream_buf)
        self._stream_buf += delta
        new_clean = strip_think(self._stream_buf)
        incremental = new_clean[len(prev_clean) :]
        if incremental:
            self._saw_stream_delta = True
            if self._turn_journal is not None:
                self._turn_journal.visible_assistant_text += incremental
                self._turn_journal.touch()
                self._loop.turn_journals.save(self._turn_journal)
            if self._on_stream:
                await self._on_stream(incremental)

    async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
        """通知外层当前一段流式输出已经收尾。"""
        del context
        if self._on_stream_end:
            await self._on_stream_end(resuming=resuming)
        self._stream_buf = ""

    @property
    def saw_stream_delta(self) -> bool:
        """返回本轮是否实际收到过正文 delta。"""
        return self._saw_stream_delta

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        """在工具执行前补一层对用户可见的进度反馈。"""
        if self._turn_journal is not None and context.response is not None:
            assistant_message = build_assistant_message(
                self._turn_journal.visible_assistant_text or context.response.content or "",
                tool_calls=[tc.to_openai_tool_call() for tc in context.tool_calls],
                reasoning_content=context.response.reasoning_content,
                reasoning_items=context.response.reasoning_items,
                thinking_blocks=context.response.thinking_blocks,
            )
            self._turn_journal.assistant_message = assistant_message
            self._turn_journal.tool_calls = [tc.to_openai_tool_call() for tc in context.tool_calls]
            self._turn_journal.tool_entries = [
                ToolJournalEntry(
                    tool_call_id=tc.id,
                    name=tc.name,
                    arguments=dict(tc.arguments),
                    status="planned",
                )
                for tc in context.tool_calls
            ]
            self._turn_journal.touch()
            self._loop.turn_journals.save(self._turn_journal)
        if self._on_progress:
            if not self._on_stream:
                thought = self._loop._strip_think(
                    context.response.content if context.response else None
                )
                if thought:
                    await self._on_progress(thought)
            tool_hint = self._loop._strip_think(self._loop._tool_hint(context.tool_calls))
            await self._on_progress(tool_hint, tool_hint=True)
        for tc in context.tool_calls:
            args_str = json.dumps(tc.arguments, ensure_ascii=False)
            logger.info("Tool call: {}({})", tc.name, args_str[:200])
        self._loop._set_tool_context(
            self._channel,
            self._chat_id,
            self._message_id,
            self._session_key,
        )

    async def after_iteration(self, context: AgentHookContext) -> None:
        """在迭代结束后统一记录 token 用量。"""
        u = context.usage or {}
        logger.debug(
            "LLM usage: prompt={} completion={} cached={}",
            u.get("prompt_tokens", 0),
            u.get("completion_tokens", 0),
            u.get("cached_tokens", 0),
        )

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        """在最终落盘前移除 think 块。"""
        del context
        return self._loop._strip_think(content)


class TurnProcessor:
    """负责单轮消息执行、会话落盘与中断收尾。"""

    def __init__(self, loop: "AgentLoop") -> None:
        """绑定所属 AgentLoop。

        参数:
            loop: 当前执行 owner 所属的主循环。

        返回:
            无返回值。
        """
        self._loop = loop

    async def run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        *,
        session: Session | None = None,
        channel: str = "cli",
        chat_id: str = "direct",
        message_id: str | None = None,
        pending_queue: asyncio.Queue | None = None,
    ) -> tuple[str | None, list[str], list[dict], str, bool, bool]:
        """执行一轮 agent tool loop。"""
        loop = self._loop
        loop_hook = _LoopHook(
            loop,
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
            channel=channel,
            chat_id=chat_id,
            message_id=message_id,
            session_key=session.key if session is not None else None,
            turn_journal=self.get_or_create_turn_journal(session),
        )
        hook: AgentHook = (
            CompositeHook([loop_hook] + loop._extra_hooks) if loop._extra_hooks else loop_hook
        )

        async def _checkpoint(payload: dict[str, Any]) -> None:
            if session is None:
                return
            self.set_runtime_checkpoint(session, payload)

        async def _tool_status(
            *,
            tool_call,
            status: str,
            result: Any,
            error: str | None,
        ) -> None:
            if session is None:
                return
            journal = self.get_or_create_turn_journal(session)
            if journal is None:
                return
            for entry in journal.tool_entries:
                if entry.tool_call_id != tool_call.id:
                    continue
                entry.status = status
                entry.result = result
                entry.error = error
                break
            else:
                journal.tool_entries.append(
                    ToolJournalEntry(
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                        arguments=dict(tool_call.arguments),
                        status=status,
                        result=result,
                        error=error,
                    )
                )
            journal.touch()
            loop.turn_journals.save(journal)

        async def _drain_pending(*, limit: int = _MAX_INJECTIONS_PER_TURN) -> list[dict[str, Any]]:
            if pending_queue is None:
                return []
            items: list[dict[str, Any]] = []
            while len(items) < limit:
                try:
                    pending_msg = pending_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                user_content = build_user_content(
                    text=pending_msg.content,
                    media=pending_msg.media if pending_msg.media else None,
                )
                runtime_ctx = build_runtime_context(
                    channel=pending_msg.channel,
                    chat_id=pending_msg.chat_id,
                    timezone=loop.context.timezone,
                )
                if isinstance(user_content, str):
                    merged: str | list[dict[str, Any]] = f"{runtime_ctx}\n\n{user_content}"
                else:
                    merged = [{"type": "text", "text": runtime_ctx}] + user_content
                items.append({"role": "user", "content": merged})
            return items

        result = await loop.runner.run(
            AgentRunSpec(
                initial_messages=initial_messages,
                tools=loop.tools,
                model=loop.model,
                max_iterations=loop.max_iterations,
                max_tool_result_chars=loop.max_tool_result_chars,
                hook=hook,
                error_message="Sorry, I encountered an error calling the AI model.",
                concurrent_tools=True,
                workspace=loop.workspace,
                session_key=session.key if session else None,
                context_window_tokens=loop.context_window_tokens,
                context_block_limit=loop.context_block_limit,
                provider_retry_mode=loop.provider_retry_mode,
                progress_callback=on_progress,
                checkpoint_callback=_checkpoint,
                injection_callback=_drain_pending,
                tool_status_callback=_tool_status,
            )
        )
        loop._state.last_usage = result.usage
        if result.stop_reason == "max_iterations":
            logger.warning("Max iterations ({}) reached", loop.max_iterations)
        elif result.stop_reason == "error":
            logger.error("LLM returned error: {}", (result.final_content or "")[:200])
        return (
            result.final_content,
            result.tools_used,
            result.messages,
            result.stop_reason,
            result.had_injections,
            loop_hook.saw_stream_delta,
        )

    async def process_message_result(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        pending_queue: asyncio.Queue | None = None,
        persist_session: bool = True,
    ) -> DirectProcessResult:
        """处理单条消息，并返回完整执行结果。"""
        loop = self._loop
        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or msg.session_key
        session = loop.sessions.get_or_create(key) if persist_session else Session(key=key)
        if persist_session and self.restore_runtime_checkpoint(session):
            loop.sessions.save(session)

        session, pending = loop.auto_compact.prepare_session(session, key)
        interrupted_context = self.build_interrupted_runtime_context(session)
        turn_journal = self.get_or_create_turn_journal(session)
        if turn_journal is not None and turn_journal.user_message is None:
            turn_journal.user_message = {
                "role": "user",
                "content": msg.content,
            }
            turn_journal.touch()
            loop.turn_journals.save(turn_journal)

        quick_action = loop.user_profile.detect_quick_action(
            session_key=key,
            text=msg.content,
        )
        if quick_action is not None:
            loop._clear_interrupt_state(key)
            if quick_action.action == "apply":
                applied = loop.user_profile.apply_candidate(quick_action.candidate.id)
                content = (
                    f"已更新 USER.md：{applied.field} -> {applied.value}"
                    if applied is not None
                    else "待确认画像不存在，无法更新。"
                )
            else:
                rejected = loop.user_profile.reject_candidate(quick_action.candidate.id)
                content = (
                    f"已忽略该画像候选：{rejected.field} -> {rejected.value}"
                    if rejected is not None
                    else "待确认画像不存在，无法忽略。"
                )
            return DirectProcessResult(
                outbound=OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=content,
                    metadata=dict(msg.metadata or {}),
                ),
                final_content=content,
                stop_reason="user_profile_quick_action",
                session_key=key,
            )

        raw = msg.content.strip()
        ctx = loop._build_command_context(msg=msg, session=session, key=key, raw=raw)
        if result := await loop.commands.dispatch(ctx):
            loop._clear_interrupt_state(key)
            return DirectProcessResult(
                outbound=result,
                final_content=result.content,
                stop_reason="command",
                session_key=key,
            )

        await loop.consolidator.maybe_consolidate_by_tokens(session)
        loop._set_tool_context(
            msg.channel,
            msg.chat_id,
            msg.metadata.get("message_id"),
            key,
        )
        self.record_explicit_skill_mentions(
            msg.content,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )

        history = session.get_history(max_messages=0)
        initial_messages = loop.context.build_messages(
            history=history,
            current_message=msg.content,
            session_summary=pending,
            media=msg.media if msg.media else None,
            attachments=msg.metadata.get("attachments"),
            channel=msg.channel,
            chat_id=msg.chat_id,
            interrupted_context=interrupted_context,
        )

        async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
            meta = dict(msg.metadata or {})
            if tool_hint:
                meta["_tool_transition"] = True
            else:
                meta["_progress"] = True
            await loop.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=content,
                    metadata=meta,
                )
            )

        final_content, tools_used, all_msgs, stop_reason, _had_injections, saw_stream_delta = (
            await self.run_agent_loop(
                initial_messages,
                on_progress=on_progress or _bus_progress,
                on_stream=on_stream,
                on_stream_end=on_stream_end,
                session=session,
                channel=msg.channel,
                chat_id=msg.chat_id,
                message_id=msg.metadata.get("message_id"),
                pending_queue=pending_queue,
            )
        )

        if final_content is None or not final_content.strip():
            final_content = EMPTY_FINAL_RESPONSE_MESSAGE

        if persist_session:
            self.save_turn(session, all_msgs, 1 + len(history))
            self.finalize_completed_turn_journal(session, final_content)
            self.clear_runtime_checkpoint(session)
            loop.sessions.save(session)
            loop._schedule_background(loop.consolidator.maybe_consolidate_by_tokens(session))

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)

        reminder = None
        if loop.user_profile.should_attempt_extraction(
            user_text=msg.content,
            assistant_text=final_content,
            stop_reason=stop_reason,
        ):
            reminder = await self._build_user_profile_reminder(
                session_key=key,
                user_text=msg.content,
                assistant_text=final_content,
                history=history,
            )
        outbound_content = final_content if reminder is None else f"{final_content}\n\n{reminder}"

        meta = dict(msg.metadata or {})
        if saw_stream_delta and stop_reason != "error":
            meta["_streamed"] = True
        loop._clear_interrupt_state(key)
        outbound = OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=outbound_content,
            metadata=meta,
        )
        return DirectProcessResult(
            outbound=outbound,
            final_content=outbound_content,
            tools_used=tools_used,
            messages=all_msgs,
            stop_reason=stop_reason,
            session_key=key,
            saw_stream_delta=saw_stream_delta,
        )

    async def process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        pending_queue: asyncio.Queue | None = None,
        persist_session: bool = True,
    ) -> OutboundMessage | None:
        """处理单条消息，并只返回对外回复。"""
        result = await self.process_message_result(
            msg,
            session_key=session_key,
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
            pending_queue=pending_queue,
            persist_session=persist_session,
        )
        return result.outbound

    def record_explicit_skill_mentions(
        self,
        current_message: str,
        *,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        """记录用户显式提到的 skill。"""
        lowered = current_message.lower()
        for skill in self._loop.skill_registry.scan():
            if skill.key.lower() in lowered or skill.metadata.name.lower() in lowered:
                self._loop.skill_registry.record_usage(
                    skill,
                    channel=channel,
                    chat_id=chat_id,
                    trigger="explicit",
                )

    async def _build_user_profile_reminder(
        self,
        *,
        session_key: str,
        user_text: str,
        assistant_text: str,
        history: list[dict[str, Any]],
    ) -> str | None:
        """抽取画像候选并返回需要附加的提醒文本。"""
        loop = self._loop
        candidates = await loop.user_profile.extract_candidates(
            session_key=session_key,
            user_text=user_text,
            assistant_text=assistant_text,
            recent_history=history,
        )
        reminder = loop.user_profile.build_reminder(
            session_key=session_key,
            new_candidates=candidates,
        )
        return reminder.text if reminder is not None else None

    def sanitize_persisted_blocks(
        self,
        content: list[dict[str, Any]],
        *,
        should_truncate_text: bool = False,
        drop_runtime: bool = False,
    ) -> list[dict[str, Any]]:
        """在写入会话前清理不适合持久化的多模态块。"""
        filtered: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                filtered.append(block)
                continue
            if (
                drop_runtime
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
                and block["text"].startswith(RUNTIME_CONTEXT_TAG)
            ):
                continue
            if (
                block.get("type") == "image_url"
                and block.get("image_url", {}).get("url", "").startswith("data:image/")
            ):
                path = (block.get("_meta") or {}).get("path", "")
                filtered.append({"type": "text", "text": image_placeholder_text(path)})
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                text = block["text"]
                if should_truncate_text and len(text) > self._loop.max_tool_result_chars:
                    text = truncate_text_fn(text, self._loop.max_tool_result_chars)
                filtered.append({**block, "text": text})
                continue
            filtered.append(block)
        return filtered

    def save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """把本轮新增消息写入 session。"""
        from datetime import datetime

        for m in messages[skip:]:
            entry = dict(m)
            role, content = entry.get("role"), entry.get("content")
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue
            if role == "tool":
                if isinstance(content, str) and len(content) > self._loop.max_tool_result_chars:
                    entry["content"] = truncate_text_fn(content, self._loop.max_tool_result_chars)
                elif isinstance(content, list):
                    filtered = self.sanitize_persisted_blocks(content, should_truncate_text=True)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            elif role == "user":
                if isinstance(content, str) and content.startswith(RUNTIME_CONTEXT_TAG):
                    end_pos = content.find(RUNTIME_CONTEXT_END)
                    if end_pos >= 0:
                        after = content[end_pos + len(RUNTIME_CONTEXT_END):].lstrip("\n")
                        if after:
                            entry["content"] = after
                        else:
                            continue
                    else:
                        after_tag = content[len(RUNTIME_CONTEXT_TAG):].lstrip("\n")
                        if after_tag.strip():
                            entry["content"] = after_tag
                        else:
                            continue
                if isinstance(content, list):
                    filtered = self.sanitize_persisted_blocks(content, drop_runtime=True)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)
        session.updated_at = datetime.now()

    @staticmethod
    def interrupted_tool_content() -> str:
        """返回未完成工具调用的统一中断占位文案。"""
        return "Interrupted: tool execution stopped before completion."

    @staticmethod
    def skipped_tool_content() -> str:
        """返回未开始执行工具的统一占位文案。"""
        return "Skipped: tool execution did not start before interruption."

    def mark_runtime_checkpoint_interrupted(
        self,
        session: Session,
        reason: InterruptReason,
    ) -> None:
        """把当前运行中检查点标记为已中断。"""
        checkpoint = session.metadata.get(self._loop._RUNTIME_CHECKPOINT_KEY)
        if not isinstance(checkpoint, dict):
            return
        checkpoint["interrupted"] = True
        checkpoint["interrupt_reason"] = reason
        session.metadata[self._loop._RUNTIME_CHECKPOINT_KEY] = checkpoint

    def finalize_interrupted_turn(
        self,
        session: Session,
        reason: InterruptReason,
    ) -> bool:
        """把当前会话上的运行中检查点收口为 interrupted 历史。"""
        journal = self._loop.turn_journals.maybe_load_from_session(session)
        if journal is not None:
            restored = self.restore_turn_journal(session, journal, reason)
            self._loop.sessions.save(session)
            return restored
        self.mark_runtime_checkpoint_interrupted(session, reason)
        restored = self.restore_runtime_checkpoint(session)
        self._loop.sessions.save(session)
        return restored

    def build_interrupted_outbound(
        self,
        msg: InboundMessage,
        reason: InterruptReason,
    ) -> OutboundMessage:
        """构造用户可见的 interrupted 终态消息。"""
        metadata = dict(msg.metadata or {})
        metadata["_interrupted"] = True
        metadata["_interrupt_reason"] = reason
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content="已中断当前回复。",
            metadata=metadata,
        )

    def set_runtime_checkpoint(self, session: Session, payload: dict[str, Any]) -> None:
        """持久化当前运行中的检查点。"""
        payload.setdefault("interrupted", False)
        payload.setdefault("interrupt_reason", None)
        session.metadata[self._loop._RUNTIME_CHECKPOINT_KEY] = payload
        self._loop.sessions.save(session)

    def clear_runtime_checkpoint(self, session: Session) -> None:
        """清除会话上的运行中检查点。"""
        if self._loop._RUNTIME_CHECKPOINT_KEY in session.metadata:
            session.metadata.pop(self._loop._RUNTIME_CHECKPOINT_KEY, None)
        clear_running_journal_metadata(session)

    @staticmethod
    def checkpoint_message_key(message: dict[str, Any]) -> tuple[Any, ...]:
        """提取检查点消息的去重键。"""
        return (
            message.get("role"),
            message.get("content"),
            message.get("tool_call_id"),
            message.get("name"),
            message.get("tool_calls"),
            message.get("reasoning_content"),
            message.get("thinking_blocks"),
        )

    def restore_runtime_checkpoint(self, session: Session) -> bool:
        """把未完成轮次的检查点物化回会话历史。"""
        journal = self._loop.turn_journals.maybe_load_from_session(session)
        if journal is not None:
            return self.restore_turn_journal(session, journal, journal.interrupt_reason)
        from datetime import datetime

        checkpoint = session.metadata.get(self._loop._RUNTIME_CHECKPOINT_KEY)
        if not isinstance(checkpoint, dict):
            return False

        assistant_message = checkpoint.get("assistant_message")
        completed_tool_results = checkpoint.get("completed_tool_results") or []
        pending_tool_calls = checkpoint.get("pending_tool_calls") or []
        restored_messages: list[dict[str, Any]] = []
        if isinstance(assistant_message, dict):
            restored = dict(assistant_message)
            restored.setdefault("timestamp", datetime.now().isoformat())
            restored_messages.append(restored)
        for message in completed_tool_results:
            if isinstance(message, dict):
                restored = dict(message)
                restored.setdefault("timestamp", datetime.now().isoformat())
                restored_messages.append(restored)
        for tool_call in pending_tool_calls:
            if not isinstance(tool_call, dict):
                continue
            tool_id = tool_call.get("id")
            name = ((tool_call.get("function") or {}).get("name")) or "tool"
            restored_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "name": name,
                    "content": self.interrupted_tool_content(),
                    "timestamp": datetime.now().isoformat(),
                }
            )

        overlap = 0
        max_overlap = min(len(session.messages), len(restored_messages))
        for size in range(max_overlap, 0, -1):
            existing = session.messages[-size:]
            restored = restored_messages[:size]
            if all(
                self.checkpoint_message_key(left) == self.checkpoint_message_key(right)
                for left, right in zip(existing, restored)
            ):
                overlap = size
                break
        session.messages.extend(restored_messages[overlap:])
        self.clear_runtime_checkpoint(session)
        return True

    def get_or_create_turn_journal(self, session: Session | None) -> TurnJournalRecord | None:
        """为当前轮获取或创建 journal。"""
        if session is None:
            return None
        existing = self._loop.turn_journals.maybe_load_from_session(session)
        if existing is not None:
            return existing
        record = self._loop.turn_journals.create(session.key)
        attach_running_journal_metadata(session, record)
        self._loop.sessions.save(session)
        return record

    def finalize_completed_turn_journal(self, session: Session, final_content: str | None) -> None:
        """在正常完成时清理 journal，并补齐 assistant 草稿。"""
        journal = self._loop.turn_journals.maybe_load_from_session(session)
        if journal is None:
            return
        journal.status = "completed"
        if final_content:
            journal.visible_assistant_text = final_content
            assistant = dict(journal.assistant_message or {})
            assistant["role"] = "assistant"
            assistant["content"] = final_content
            journal.assistant_message = assistant
        self._loop.turn_journals.delete(journal.session_key, journal.turn_id)
        clear_running_journal_metadata(session)

    def build_interrupted_runtime_context(self, session: Session) -> str | None:
        """构造短期中断续接提示。"""
        payload = consume_previous_interrupted_metadata(session)
        if not payload:
            return None
        reason = str(payload.get("interrupt_reason") or "unknown")
        turn_id = str(payload.get("turn_id") or "")
        self._loop.sessions.save(session)
        return (
            "上一轮回复被中断，不是正常结束。\n"
            "已展示给用户的正文已写入历史。\n"
            "部分工具可能已完成，部分可能已中断或未执行。\n"
            f"中断原因：{reason}\n"
            f"turn_id：{turn_id}"
        )

    def restore_turn_journal(
        self,
        session: Session,
        journal: TurnJournalRecord,
        reason: InterruptReason | str | None,
    ) -> bool:
        """把 turn journal 物化成主会话历史。"""
        from datetime import datetime

        journal.status = "interrupted"
        journal.interrupt_reason = str(reason or journal.interrupt_reason or "user_interrupt")
        for entry in journal.tool_entries:
            if entry.status in {"succeeded", "failed"}:
                continue
            if entry.status == "running":
                entry.status = "interrupted"
                continue
            entry.status = "skipped"
        restored_messages: list[dict[str, Any]] = []

        user_message = journal.user_message or {}
        user_content = user_message.get("content")
        if isinstance(user_content, str) and user_content.strip():
            restored_messages.append(
                {
                    "role": "user",
                    "content": user_content,
                    "timestamp": datetime.now().isoformat(),
                }
            )

        assistant_message = journal.assistant_message or {}
        visible_content = journal.visible_assistant_text
        has_tool_calls = bool(assistant_message.get("tool_calls") or journal.tool_calls)
        if visible_content or has_tool_calls:
            restored_assistant = build_assistant_message(
                visible_content or assistant_message.get("content") or "",
                tool_calls=list(assistant_message.get("tool_calls") or journal.tool_calls or []),
                reasoning_content=assistant_message.get("reasoning_content"),
                reasoning_items=assistant_message.get("reasoning_items"),
                thinking_blocks=assistant_message.get("thinking_blocks"),
            )
            restored_assistant["timestamp"] = datetime.now().isoformat()
            restored_messages.append(restored_assistant)

        for entry in journal.tool_entries:
            content = entry.result
            if entry.status == "interrupted":
                content = self.interrupted_tool_content()
            elif entry.status == "skipped":
                content = self.skipped_tool_content()
            elif entry.status == "failed":
                content = entry.error or "Error: tool execution failed."
            restored_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": entry.tool_call_id,
                    "name": entry.name,
                    "content": content,
                    "timestamp": datetime.now().isoformat(),
                    "status": entry.status,
                    "arguments": entry.arguments,
                }
            )

        overlap = 0
        max_overlap = min(len(session.messages), len(restored_messages))
        for size in range(max_overlap, 0, -1):
            existing = session.messages[-size:]
            restored = restored_messages[:size]
            if all(
                self.checkpoint_message_key(left) == self.checkpoint_message_key(right)
                for left, right in zip(existing, restored)
            ):
                overlap = size
                break
        session.messages.extend(restored_messages[overlap:])
        set_previous_interrupted_metadata(
            session,
            turn_id=journal.turn_id,
            reason=journal.interrupt_reason,
        )
        self.clear_runtime_checkpoint(session)
        self._loop.turn_journals.delete(journal.session_key, journal.turn_id)
        return True
