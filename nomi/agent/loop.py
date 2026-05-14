"""承载 Nomi 主链路的 Agent 执行循环。"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from nomi import __version__
from nomi.agent.context.builder import ContextBuilder
from nomi.agent.execution.processor import DirectProcessResult, TurnProcessor
from nomi.agent.execution.runner import AgentRunner
from nomi.agent.execution.turn_journal import TurnJournalStore
from nomi.agent.hook import AgentHook
from nomi.agent.loop_runtime.background import BackgroundRuntime
from nomi.agent.loop_runtime.control import LoopControl, LoopMcpSupport
from nomi.agent.loop_runtime.dispatch import DispatchRuntime
from nomi.agent.loop_runtime.state import LoopRuntimeState, SessionInterruptState
from nomi.agent.memory.autocompact import AutoCompact
from nomi.agent.memory.consolidator import Consolidator
from nomi.agent.memory.dream import Dream
from nomi.agent.memory.profile import UserProfileService
from nomi.agent.memory.store import MemoryStore
from nomi.agent.skills.registry import SkillRegistry
from nomi.agent.tools.bootstrap import register_default_tools
from nomi.agent.tools.registry import ToolRegistry
from nomi.bus.events import InboundMessage, OutboundMessage
from nomi.bus.queue import MessageBus
from nomi.command import CommandContext, CommandRouter, register_builtin_commands
from nomi.config.paths import get_cron_store_path, get_data_dir, get_skills_dir, get_task_store_path
from nomi.config.schema import AgentDefaults, Config
from nomi.cron import CronJob, CronService
from nomi.providers.base import LLMProvider
from nomi.runtime.models import InterruptReason, InterruptResult
from nomi.session.manager import Session, SessionManager
from nomi.tasks import TaskRunner, TaskStore
from nomi.utils.text import strip_think

if TYPE_CHECKING:
    from nomi.config.schema import ExecToolConfig, WebToolsConfig


UNIFIED_SESSION_KEY = "unified:default"


class LoopStatusSnapshot:
    """描述一份会话级运行状态快照。"""

    def __init__(
        self,
        *,
        version: str,
        model: str,
        start_time: float,
        last_usage: dict[str, int],
        context_window_tokens: int,
        session_msg_count: int,
        context_tokens_estimate: int,
        search_usage_text: str | None = None,
    ) -> None:
        """保存一份会话级状态快照。

        参数:
            version: 当前版本号。
            model: 当前默认模型。
            start_time: 主循环启动时间戳。
            last_usage: 最近一次模型用量。
            context_window_tokens: 当前上下文窗口上限。
            session_msg_count: 当前会话消息数。
            context_tokens_estimate: 估算的上下文 token 数。
            search_usage_text: 可选的搜索额度说明。

        返回:
            无返回值。
        """
        self.version = version
        self.model = model
        self.start_time = start_time
        self.last_usage = last_usage
        self.context_window_tokens = context_window_tokens
        self.session_msg_count = session_msg_count
        self.context_tokens_estimate = context_tokens_estimate
        self.search_usage_text = search_usage_text


class AgentLoop:
    """负责把消息总线、会话、Provider 和工具闭环串成主执行链路。"""

    _RUNTIME_CHECKPOINT_KEY = "runtime_checkpoint"

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int | None = None,
        context_window_tokens: int | None = None,
        context_block_limit: int | None = None,
        max_tool_result_chars: int | None = None,
        provider_retry_mode: str = "standard",
        web_config: WebToolsConfig | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        timezone: str | None = None,
        idle_compact_after_minutes: int = 0,
        hooks: list[AgentHook] | None = None,
        unified_session: bool = False,
        reminder_consumer: str | None = None,
        config: Config | None = None,
    ):
        """初始化主链路运行时依赖。"""
        from nomi.config.schema import ExecToolConfig, WebToolsConfig

        defaults = AgentDefaults()
        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.reminder_consumer = str(reminder_consumer or "").strip() or None
        self.reminder_consumers: set[str] = set()
        if self.reminder_consumer:
            self.reminder_consumers.add(self.reminder_consumer)
        self.model = model or provider.get_default_model()
        self.max_iterations = (
            max_iterations if max_iterations is not None else defaults.max_tool_iterations
        )
        self.context_window_tokens = (
            context_window_tokens
            if context_window_tokens is not None
            else defaults.context_window_tokens
        )
        self.context_block_limit = context_block_limit
        self.max_tool_result_chars = (
            max_tool_result_chars
            if max_tool_result_chars is not None
            else defaults.max_tool_result_chars
        )
        self.provider_retry_mode = provider_retry_mode
        self.web_config = web_config or WebToolsConfig()
        self.exec_config = exec_config or ExecToolConfig()
        self.config = config
        self.restrict_to_workspace = restrict_to_workspace
        self._extra_hooks: list[AgentHook] = hooks or []
        self._state = LoopRuntimeState()
        self._control = LoopControl(self, self._state)
        self._mcp = LoopMcpSupport(self, self._state)

        self.memory_store = MemoryStore(workspace)
        self.memory_store.ensure_user_profile_initialized()
        self.skill_registry = SkillRegistry()
        self.context = ContextBuilder(
            workspace,
            memory_store=self.memory_store,
            skill_registry=self.skill_registry,
            timezone=timezone,
        )
        self.sessions = session_manager or SessionManager(get_data_dir())
        self.turn_journals = TurnJournalStore(workspace)
        self.tools = ToolRegistry()
        self.runner = AgentRunner(provider)
        self._unified_session = unified_session
        self._mcp_servers = mcp_servers or {}
        default_timezone = self.context.timezone or "Asia/Shanghai"
        self.cron_service = cron_service or CronService(
            get_cron_store_path(self.workspace),
            default_timezone=default_timezone,
        )
        self.task_store = TaskStore(get_task_store_path(self.workspace))
        self.tasks = TaskRunner(self, self.task_store, self.cron_service)
        max_concurrency = int(os.environ.get("NANOBOT_MAX_CONCURRENT_REQUESTS", "3"))
        self._concurrency_gate: asyncio.Semaphore | None = (
            asyncio.Semaphore(max_concurrency) if max_concurrency > 0 else None
        )
        self.consolidator = Consolidator(
            store=self.memory_store,
            provider=provider,
            model=self.model,
            sessions=self.sessions,
            context_window_tokens=context_window_tokens,
            build_messages=self.context.build_messages,
            get_tool_definitions=self.tools.get_definitions,
            max_completion_tokens=provider.generation.max_tokens,
        )
        self.auto_compact = AutoCompact(
            sessions=self.sessions,
            consolidator=self.consolidator,
            idle_compact_after_minutes=idle_compact_after_minutes,
        )
        self.dream = Dream(
            store=self.memory_store,
            provider=provider,
            model=self.model,
        )
        self.user_profile = UserProfileService(
            store=self.memory_store,
            provider=provider,
            model=self.model,
        )
        self.instance_relation_quick_action_handler = None
        register_default_tools(
            registry=self.tools,
            workspace=self.workspace,
            exec_config=self.exec_config,
            web_config=self.web_config,
            restrict_to_workspace=self.restrict_to_workspace,
            task_runner=self.tasks,
            provider=provider,
            model=self.model,
            default_timezone=default_timezone,
            extra_allowed_dirs=[get_skills_dir()],
            sessions=self.sessions,
        )
        self.commands = CommandRouter()
        register_builtin_commands(self.commands)

        self._turns = TurnProcessor(self)
        self._dispatch_runtime = DispatchRuntime(self)
        self._background = BackgroundRuntime(self)
        self.cron_service.on_job = self._run_cron_job

    def _find_latest_session_for_channel(self, channel: str) -> str | None:
        """返回指定渠道最近活跃的会话键。"""
        normalized = str(channel or "").strip()
        if not normalized:
            return None
        for item in self.sessions.list_sessions():
            session_id = str(item.get("session_id") or item.get("key") or "").strip()
            source = str(item.get("source") or "").strip()
            if not session_id:
                continue
            if source == normalized or session_id.startswith(f"{normalized}:"):
                return session_id
        return None

    async def poll_global_reminders(self) -> bool:
        """按当前 runtime 挂载入口消费实例级全局提醒。"""
        consumers = sorted(self.reminder_consumers)
        if not consumers:
            return False
        published = False
        for consumer in consumers:
            published = await AgentLoop._poll_global_reminders_for_consumer(self, consumer) or published
        return published

    async def _poll_global_reminders_for_consumer(self, consumer: str) -> bool:
        """按单个 consumer 投递尚未发送的全局提醒。"""
        published = False
        for reminder in self.tasks.list_pending_reminders(consumer):
            if consumer == "remote":
                message = OutboundMessage(
                    channel="remote",
                    chat_id=reminder.session_id,
                    content=reminder.content,
                    metadata={
                        "_task_delivery_id": reminder.task_id,
                        "_global_reminder_broadcast": True,
                        "_session_id": reminder.session_id,
                    },
                )
            elif consumer == "cli":
                message = OutboundMessage(
                    channel="cli",
                    chat_id="direct",
                    content=reminder.content,
                    metadata={
                        "_task_delivery_id": reminder.task_id,
                        "_session_id": "cli:direct",
                    },
                )
            else:
                session_id = self._find_latest_session_for_channel(consumer)
                if session_id is None:
                    continue
                _channel, chat_id = session_id.split(":", 1)
                message = OutboundMessage(
                    channel=consumer,
                    chat_id=chat_id,
                    content=reminder.content,
                    metadata={
                        "_task_delivery_id": reminder.task_id,
                        "_session_id": session_id,
                    },
                )
            await self.bus.publish_outbound(message)
            self.tasks.mark_reminder_delivered(reminder.id, consumer)
            published = True
        return published

    def set_reminder_consumers(self, consumers: list[str] | tuple[str, ...] | set[str]) -> None:
        """设置当前 runtime 已挂载的提醒消费入口。"""
        self.reminder_consumers = {
            str(consumer or "").strip()
            for consumer in consumers
            if str(consumer or "").strip()
        }
        self.reminder_consumer = next(iter(sorted(self.reminder_consumers)), None)
        self.tasks.set_scheduler_owner_name("runtime")

    async def cancel_session_tasks(self, session_key: str) -> int:
        """取消指定会话下的活跃任务。"""
        return await self._control.cancel_session_tasks(session_key)

    async def refresh_mcp_servers(self, mcp_servers: dict | None) -> None:
        """刷新当前运行时可见的 MCP server 配置。"""
        self._mcp_servers = mcp_servers or {}
        await self._mcp.close()
        await self._mcp.connect()

    def drop_pending_session_messages(self, session_key: str) -> int:
        """丢弃指定会话当前待注入的新消息。"""
        normalized = self._normalize_control_session_key(session_key)
        return self._control.drop_pending_queue(normalized)

    def interrupt_session(
        self,
        session_key: str,
        reason: InterruptReason = "user_interrupt",
    ) -> InterruptResult:
        """向指定会话发出一次显式中断请求。"""
        result = self._control.interrupt_session(session_key, reason)
        return result

    def _peek_interrupt_state(self, session_key: str) -> SessionInterruptState | None:
        """读取当前会话的挂起中断请求。"""
        return self._control.peek_interrupt_state(session_key)

    def _consume_interrupt_state(self, session_key: str) -> SessionInterruptState | None:
        """消费并清理当前会话的挂起中断请求。"""
        return self._control.consume_interrupt_state(session_key)

    def _clear_interrupt_state(self, session_key: str) -> None:
        """清理当前会话的中断请求状态。"""
        self._control.clear_interrupt_state(session_key)

    def _normalize_control_session_key(self, session_key: str) -> str:
        """把控制面会话键归一化到实际的运行态键值。"""
        if self._unified_session and session_key != UNIFIED_SESSION_KEY:
            return UNIFIED_SESSION_KEY
        return session_key

    def reset_session(self, session_key: str) -> None:
        """清空指定会话，并把未归档消息转入后台摘要。"""
        session = self.sessions.get_or_create(session_key)
        snapshot = session.messages[session.last_consolidated :]
        session.clear(clear_metadata=True)
        self.sessions.save(session)
        self.sessions.invalidate(session.key)
        if snapshot:
            self._schedule_background(self.consolidator.archive(snapshot))

    async def build_status_snapshot(self, session_key: str) -> LoopStatusSnapshot:
        """构造当前会话的运行状态快照。"""
        session = self.sessions.get_or_create(session_key)
        context_tokens_estimate = 0
        try:
            context_tokens_estimate, _ = self.consolidator.estimate_session_prompt_tokens(session)
        except Exception:
            pass
        if context_tokens_estimate <= 0:
            context_tokens_estimate = self._state.last_usage.get("prompt_tokens", 0)

        search_usage_text: str | None = None
        try:
            from nomi.utils.searchusage import fetch_search_usage

            search_config = getattr(self.web_config, "search", None)
            if search_config is not None:
                usage = await fetch_search_usage(
                    provider=getattr(search_config, "provider", "duckduckgo"),
                    api_key=getattr(search_config, "api_key", "") or None,
                )
                search_usage_text = usage.format()
        except Exception:
            pass

        return LoopStatusSnapshot(
            version=__version__,
            model=self.model,
            start_time=self._state.start_time,
            last_usage=dict(self._state.last_usage),
            context_window_tokens=self.context_window_tokens,
            session_msg_count=len(session.get_history(max_messages=0)),
            context_tokens_estimate=context_tokens_estimate,
            search_usage_text=search_usage_text,
        )

    def trigger_dream_background(self, channel: str, chat_id: str) -> None:
        """在后台触发一次 Dream。"""
        self._background.trigger_dream_background(channel, chat_id)

    def list_tasks(self, include_disabled: bool = False):
        """列出当前任务。"""
        return self.tasks.list_tasks(include_disabled=include_disabled)

    def remove_task(self, task_id: str) -> bool:
        """删除指定任务。"""
        return self.tasks.delete_task(task_id)

    async def _run_cron_job(self, job: CronJob) -> None:
        """处理一条已到点时间触发记录。"""
        await self._background.run_trigger(job)

    async def _connect_mcp(self) -> None:
        """按需连接 MCP servers。"""
        await self._background.connect_mcp()

    def _build_command_context(
        self,
        *,
        msg: InboundMessage,
        session: Session | None,
        key: str,
        raw: str,
    ) -> CommandContext:
        """构造命令分发上下文。"""
        return CommandContext(msg=msg, session=session, key=key, raw=raw, loop=self)

    def _set_tool_context(
        self,
        channel: str,
        chat_id: str,
        message_id: str | None = None,
        session_key: str | None = None,
    ) -> None:
        """更新本轮工具执行上下文。"""
        for name in self.tools.tool_names:
            tool = self.tools.get(name)
            setter = getattr(tool, "set_context", None)
            if not callable(setter):
                continue
            try:
                setter(channel, chat_id, message_id, session_key)
            except TypeError:
                try:
                    setter(channel, chat_id, message_id)
                except TypeError:
                    setter(channel, chat_id)

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """移除模型正文中的 think 块。"""
        if not text:
            return None
        return strip_think(text) or None

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """格式化工具提示。"""
        from nomi.utils.tool_hints import format_tool_hints

        return format_tool_hints(tool_calls)

    def _effective_session_key(self, msg: InboundMessage) -> str:
        """返回当前消息真实用于运行态路由的 session key。"""
        if self._unified_session and not msg.session_key_override:
            return UNIFIED_SESSION_KEY
        return msg.session_key

    async def run(self) -> None:
        """持续消费消息总线并分发任务。"""
        await self._dispatch_runtime.run()

    async def _dispatch(self, msg: InboundMessage) -> None:
        """处理一条入站消息。"""
        await self._dispatch_runtime.dispatch(msg)

    async def close_mcp(self) -> None:
        """关闭前清空后台任务并释放 MCP 连接。"""
        await self.tasks.stop_scheduler()
        await self._background.close()

    def _schedule_background(self, coro) -> None:
        """登记后台协程，并在关闭时统一等待。"""
        self._control.schedule_background(coro)

    def stop(self) -> None:
        """停止主循环并阻止继续消费新消息。"""
        self._control.stop()

    async def _process_message_result(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        history_session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        pending_queue: asyncio.Queue | None = None,
        persist_session: bool = True,
    ) -> DirectProcessResult:
        """处理单条消息，并返回完整执行结果。"""
        return await self._turns.process_message_result(
            msg,
            session_key=session_key,
            history_session_key=history_session_key,
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
            pending_queue=pending_queue,
            persist_session=persist_session,
        )

    def _record_explicit_skill_mentions(
        self,
        current_message: str,
        *,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        """记录用户显式提到的 skill。"""
        self._turns.record_explicit_skill_mentions(
            current_message,
            channel=channel,
            chat_id=chat_id,
        )

    async def _process_message(
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
        return await self._turns.process_message(
            msg,
            session_key=session_key,
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
            pending_queue=pending_queue,
            persist_session=persist_session,
        )

    def _sanitize_persisted_blocks(
        self,
        content: list[dict],
        *,
        should_truncate_text: bool = False,
        drop_runtime: bool = False,
    ) -> list[dict]:
        """在写入会话前清理不适合持久化的多模态块。"""
        return self._turns.sanitize_persisted_blocks(
            content,
            should_truncate_text=should_truncate_text,
            drop_runtime=drop_runtime,
        )

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """把本轮新增消息写入 session。"""
        self._turns.save_turn(session, messages, skip)

    @staticmethod
    def _interrupted_tool_content() -> str:
        """返回未完成工具调用的统一中断占位文案。"""
        return TurnProcessor.interrupted_tool_content()

    def _mark_runtime_checkpoint_interrupted(
        self,
        session: Session,
        reason: InterruptReason,
    ) -> None:
        """把当前运行中检查点标记为已中断。"""
        self._turns.mark_runtime_checkpoint_interrupted(session, reason)

    def _finalize_interrupted_turn(
        self,
        session: Session,
        reason: InterruptReason,
    ) -> bool:
        """把当前会话上的运行中检查点收口为 interrupted 历史。"""
        return self._turns.finalize_interrupted_turn(session, reason)

    def _build_interrupted_outbound(
        self,
        msg: InboundMessage,
        reason: InterruptReason,
    ) -> OutboundMessage:
        """构造用户可见的 interrupted 终态消息。"""
        return self._turns.build_interrupted_outbound(msg, reason)

    def _set_runtime_checkpoint(self, session: Session, payload: dict) -> None:
        """持久化当前运行中的检查点。"""
        self._turns.set_runtime_checkpoint(session, payload)

    def _clear_runtime_checkpoint(self, session: Session) -> None:
        """清除会话上的运行中检查点。"""
        self._turns.clear_runtime_checkpoint(session)

    @staticmethod
    def _checkpoint_message_key(message: dict) -> tuple:
        """提取检查点消息的去重键。"""
        return TurnProcessor.checkpoint_message_key(message)

    def _restore_runtime_checkpoint(self, session: Session) -> bool:
        """把未完成轮次的检查点物化回会话历史。"""
        return self._turns.restore_runtime_checkpoint(session)

    async def _run_agent_loop(
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
        return await self._turns.run_agent_loop(
            initial_messages,
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
            session=session,
            channel=channel,
            chat_id=chat_id,
            message_id=message_id,
            pending_queue=pending_queue,
        )

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """直接处理一条消息，并返回对外回复。"""
        result = await self.process_direct_result(
            content,
            session_key=session_key,
            channel=channel,
            chat_id=chat_id,
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
        )
        return result.outbound

    async def process_direct_result(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        sender_id: str = "user",
        metadata: dict | None = None,
        history_session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        persist_session: bool = True,
    ) -> DirectProcessResult:
        """直接处理一条消息，并返回完整执行结果。"""
        return await self._dispatch_runtime.process_direct_result(
            content,
            session_key=session_key,
            channel=channel,
            chat_id=chat_id,
            sender_id=sender_id,
            metadata=metadata,
            history_session_key=history_session_key,
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
            persist_session=persist_session,
        )

    @staticmethod
    def _now() -> float:
        """返回当前时间戳。"""
        return time.time()
