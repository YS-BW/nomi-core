"""提供可复用的 Nomi 进程内 runtime 入口。"""

from __future__ import annotations

import base64
import json
import shutil
from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import TYPE_CHECKING

from nomi.agent.loop import AgentLoop
from nomi.agent.skills.manager import SkillManager
from nomi.bus.events import InboundMessage, OutboundMessage
from nomi.bus.queue import MessageBus
from nomi.config.loader import get_config_path, load_config, save_config
from nomi.config.paths import get_data_dir
from nomi.config.schema import Config
from nomi.config.schema.tools import MCPServerConfig
from nomi.providers.base import LLMProvider
from nomi.providers.capabilities.transcription import build_transcription_provider
from nomi.providers.factory.build import build_provider
from nomi.runtime.lifecycle import RuntimeLifecycle
from nomi.runtime.models import (
    DreamLogResult,
    DreamRestoreResult,
    InterruptReason,
    InterruptResult,
    RuntimeStatusSnapshot,
)
from nomi.runtime.state import RuntimeState
from nomi.session.errors import InvalidPageTokenError, SessionNotFoundError
from nomi.session.manager import Session

if TYPE_CHECKING:
    from nomi.providers.base import LLMProvider


class NomiRuntime:
    """封装 CLI 可复用的进程内 runtime 入口。"""

    def __init__(self, state: RuntimeState) -> None:
        """绑定 runtime 的共享状态和生命周期对象。

        参数:
            state: 已装配完成的 runtime 状态。

        返回:
            无返回值。
        """
        self.state = state
        self.lifecycle = RuntimeLifecycle(state)

    @classmethod
    def from_config(
        cls,
        config: Config,
        *,
        provider_builder: Callable[[Config], LLMProvider] | None = None,
        bus_factory: Callable[[], MessageBus] | None = None,
        agent_loop_factory: Callable[..., AgentLoop] | None = None,
    ) -> "NomiRuntime":
        """从配置对象装配一份完整 runtime。

        参数:
            config: 已完成环境变量展开和命令行覆盖的配置对象。
            provider_builder: 自定义 provider 构建函数，便于入口层复用现有校验逻辑。
            bus_factory: 自定义总线工厂，便于测试或上层注入。
            agent_loop_factory: 自定义主循环工厂，便于测试或入口层替换。

        返回:
            一份可直接启动或执行单次调用的 runtime。
        """
        resolved_provider_builder = provider_builder or build_provider
        resolved_bus_factory = bus_factory or MessageBus
        resolved_agent_loop_factory = agent_loop_factory or AgentLoop

        bus = resolved_bus_factory()
        provider = resolved_provider_builder(config)
        transcription_provider = build_transcription_provider(config)
        defaults = config.agents.defaults
        agent_loop = resolved_agent_loop_factory(
            bus=bus,
            provider=provider,
            workspace=config.workspace_path,
            model=defaults.model,
            max_iterations=defaults.max_tool_iterations,
            context_window_tokens=defaults.context_window_tokens,
            web_config=config.tools.web,
            context_block_limit=defaults.context_block_limit,
            max_tool_result_chars=defaults.max_tool_result_chars,
            provider_retry_mode=defaults.provider_retry_mode,
            exec_config=config.tools.exec,
            restrict_to_workspace=config.tools.restrict_to_workspace,
            mcp_servers=config.tools.mcp_servers,
            timezone=defaults.timezone,
            unified_session=defaults.unified_session,
            idle_compact_after_minutes=defaults.idle_compact_after_minutes,
        )
        return cls(
            RuntimeState(
                config=config,
                bus=bus,
                provider=provider,
                agent_loop=agent_loop,
                transcription_provider=transcription_provider,
            )
        )

    @property
    def bus(self) -> MessageBus:
        """返回 runtime 持有的消息总线。

        参数:
            无。

        返回:
            当前 runtime 的消息总线实例。
        """
        return self.state.bus

    @property
    def agent_loop(self) -> AgentLoop:
        """返回 runtime 持有的主循环对象。

        参数:
            无。

        返回:
            当前 runtime 的 AgentLoop 实例。
        """
        return self.state.agent_loop

    def interrupt_session(
        self,
        session_id: str,
        reason: InterruptReason = "user_interrupt",
    ) -> InterruptResult:
        """向指定会话发出中断请求。

        参数:
            session_id: 目标会话键。
            reason: 本次中断的触发原因。

        返回:
            当前中断请求的处理结果。
        """
        self._require_existing_session(session_id)
        return self.agent_loop.interrupt_session(session_id, reason)

    def reset_session(self, session_id: str) -> None:
        """重置指定会话。

        参数:
            session_id: 目标会话键。

        返回:
            无返回值。
        """
        self.agent_loop.reset_session(session_id)

    def drop_pending_session_messages(self, session_id: str) -> int:
        """丢弃指定会话当前待注入的新消息。"""
        return self.agent_loop.drop_pending_session_messages(session_id)

    async def get_status_snapshot(self, session_id: str) -> RuntimeStatusSnapshot:
        """获取指定会话的运行状态快照。

        参数:
            session_id: 目标会话键。

        返回:
            对外可复用的 runtime 状态快照。
        """
        self._require_existing_session(session_id)
        snapshot = await self.agent_loop.build_status_snapshot(session_id)
        return RuntimeStatusSnapshot(
            version=snapshot.version,
            model=snapshot.model,
            start_time=snapshot.start_time,
            last_usage=snapshot.last_usage,
            context_window_tokens=snapshot.context_window_tokens,
            session_msg_count=snapshot.session_msg_count,
            context_tokens_estimate=snapshot.context_tokens_estimate,
            search_usage_text=snapshot.search_usage_text,
        )

    def trigger_dream(self, channel: str, chat_id: str) -> None:
        """在后台触发一次 Dream。

        参数:
            channel: 结果回推的消息渠道。
            chat_id: 结果回推的会话标识。

        返回:
            无返回值。
        """
        self.agent_loop.trigger_dream_background(channel, chat_id)

    def list_tasks(self, include_disabled: bool = False):
        """列出当前自动任务。

        参数:
            include_disabled: 是否包含已禁用任务。

        返回:
            当前任务列表。
        """
        return self.agent_loop.list_tasks(include_disabled=include_disabled)

    def remove_task(self, task_id: str) -> bool:
        """删除指定自动任务。

        参数:
            task_id: 目标任务标识。

        返回:
            删除成功时返回 ``True``。
        """
        return self.agent_loop.remove_task(task_id)

    async def transcribe_audio(self, file_path: str) -> str:
        """通过 runtime 级 provider 转写一段音频。

        参数:
            file_path: 本地音频文件路径。

        返回:
            转写文本；未配置 provider 或转写失败时返回空字符串。
        """
        provider = self.state.transcription_provider
        if provider is None:
            return ""
        return await provider.transcribe(file_path)


    def get_dream_log(self, sha: str | None = None) -> DreamLogResult:
        """查看最近一次或指定 Dream 版本差异。

        参数:
            sha: 可选的目标提交 SHA。

        返回:
            对外可复用的 Dream 日志结果。
        """
        result = self.agent_loop.memory_store.show_dream_version(sha)
        commit = result.commit
        return DreamLogResult(
            status=result.status,
            requested_sha=result.requested_sha,
            sha=commit.sha if commit else None,
            timestamp=commit.timestamp if commit else None,
            message=commit.message if commit else result.message,
            diff=result.diff,
            changed_files=result.changed_files,
        )

    def restore_dream_version(self, sha: str) -> DreamRestoreResult:
        """恢复指定 Dream 版本。

        参数:
            sha: 需要回退的 Dream 提交 SHA。

        返回:
            对外可复用的 Dream 恢复结果。
        """
        result = self.agent_loop.memory_store.restore_dream_version(sha)
        return DreamRestoreResult(
            status=result.status,
            requested_sha=result.requested_sha,
            new_sha=result.new_sha,
            changed_files=result.changed_files,
            message=result.message,
        )

    async def run_once(
        self,
        message: str,
        *,
        session_id: str,
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """执行一次直连消息处理。

        参数:
            message: 本轮用户输入。
            session_id: 要写入的会话标识。
            on_progress: 进度回调。
            on_stream: 流式增量回调。
            on_stream_end: 流式结束回调。

        返回:
            主链路生成的标准出站消息；如果没有正文则可能返回 `None`。
        """
        return await self.agent_loop.process_direct(
            message,
            session_id,
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
        )

    async def send_user_message(
        self,
        session_id: str,
        content: str,
        *,
        client_id: str,
        metadata: dict | None = None,
    ) -> None:
        """把一条远程用户消息注入到 runtime 主链路。

        参数:
            session_id: 目标会话键。
            content: 用户输入正文。
            client_id: 发送方标识。
            metadata: 可选附加元数据。

        返回:
            无返回值。
        """
        self._require_existing_session(session_id)
        channel, chat_id = self._split_session_id(session_id)
        inbound_metadata = dict(metadata or {})
        inbound_metadata["_session_id"] = session_id
        inbound_metadata["_wants_stream"] = True
        await self.bus.publish_inbound(
            InboundMessage(
                channel=channel,
                sender_id=client_id,
                chat_id=chat_id,
                content=content,
                metadata=inbound_metadata,
                session_key_override=session_id,
            )
        )

    def list_sessions(
        self,
        *,
        page_token: str | None = None,
        page_size: int | None = None,
        include_archived: bool | None = None,
    ) -> dict:
        """按 remote 视图列出当前已持久化会话。"""
        sessions = self.agent_loop.sessions.list_sessions()
        if not include_archived:
            sessions = [item for item in sessions if not bool(item.get("archived"))]
        sessions = sorted(
            sessions,
            key=lambda item: (
                -(int(item.get("updated_at_ms") or 0)),
                str(item.get("session_id") or item.get("key") or ""),
            ),
        )

        cursor = self._decode_session_page_token(page_token)
        start_index = 0
        if cursor is not None:
            start_index = len(sessions)
            for index, item in enumerate(sessions):
                if self._is_session_after_cursor(item, cursor):
                    start_index = index
                    break

        page_items = sessions[start_index:]
        if page_size is not None and page_size > 0:
            page_items = page_items[:page_size]

        next_page_token: str | None = None
        if page_items:
            last_item = page_items[-1]
            last_index = start_index + len(page_items)
            if last_index < len(sessions):
                next_page_token = self._encode_session_page_token(
                    updated_at_ms=int(last_item.get("updated_at_ms") or 0),
                    session_id=str(last_item.get("session_id") or last_item.get("key") or ""),
                )

        return {
            "sessions": page_items,
            "next_page_token": next_page_token,
            "total_count": len(sessions),
        }

    def create_session(
        self,
        session_id: str | None = None,
        *,
        title: str | None = None,
    ) -> dict:
        """创建一条新的远程会话。"""
        session = self.agent_loop.sessions.create_session(session_id, title=title, source="remote")
        return self._serialize_session_summary(session)

    def delete_session(self, session_id: str) -> dict:
        """删除一条远程会话。"""
        deleted = self.agent_loop.sessions.delete_session(session_id)
        return {"session_id": session_id, "deleted": deleted}

    def load_session_messages(
        self,
        session_id: str,
        *,
        limit: int = 100,
        cursor: int | None = None,
    ) -> dict:
        """加载一段可供远程前端展示的会话历史。

        参数:
            session_id: 目标会话键。
            limit: 最多返回多少条消息。
            cursor: 可选的结束游标，表示从历史头部数起的独占结束索引。

        返回:
            包含消息切片和下一游标的字典。
        """
        session = self._require_existing_session(session_id)
        normalized = self._normalize_session_messages_for_history(session)
        total = len(normalized)
        end = total if cursor is None else max(0, min(cursor, total))
        start = max(0, end - max(1, limit))
        items = deepcopy(normalized[start:end])
        next_cursor = start if start > 0 else None
        return {
            "session_id": session_id,
            "messages": items,
            "cursor": end,
            "next_cursor": next_cursor,
            "total_messages": total,
        }

    def _require_existing_session(self, session_id: str) -> Session:
        """读取一条已存在会话，不存在时抛结构化错误。"""
        session = self.agent_loop.sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError("session not found", session_id=session_id)
        return session

    def get_sidebar_snapshot(self) -> dict:
        """返回远端资源侧栏快照。"""
        return {
            "tasks": self._build_sidebar_tasks(),
            "skills": self._build_sidebar_skills(),
            "mcpServers": self._build_sidebar_mcp_servers(),
        }

    def create_task_after(
        self,
        session_id: str,
        *,
        instruction: str,
        after_seconds: int,
    ) -> dict:
        """创建一次性延时任务。"""
        channel, chat_id = self._split_session_id(session_id)
        task = self.agent_loop.tasks.create_after_task(
            instruction=instruction,
            after_seconds=after_seconds,
            source_session_key=session_id,
            channel=channel,
            chat_id=chat_id,
        )
        return self._serialize_task(task)

    def create_task_at(
        self,
        session_id: str,
        *,
        instruction: str,
        at: str,
    ) -> dict:
        """创建一次性定点任务。"""
        channel, chat_id = self._split_session_id(session_id)
        task = self.agent_loop.tasks.create_at_task(
            instruction=instruction,
            at=at,
            source_session_key=session_id,
            channel=channel,
            chat_id=chat_id,
        )
        return self._serialize_task(task)

    def create_task_daily(
        self,
        session_id: str,
        *,
        instruction: str,
        daily_time: str,
    ) -> dict:
        """创建每日任务。"""
        channel, chat_id = self._split_session_id(session_id)
        task = self.agent_loop.tasks.create_daily_task(
            instruction=instruction,
            daily_time=daily_time,
            source_session_key=session_id,
            channel=channel,
            chat_id=chat_id,
        )
        return self._serialize_task(task)

    def create_task_every(
        self,
        session_id: str,
        *,
        instruction: str,
        every_seconds: int,
    ) -> dict:
        """创建固定间隔任务。"""
        channel, chat_id = self._split_session_id(session_id)
        task = self.agent_loop.tasks.create_every_task(
            instruction=instruction,
            every_seconds=every_seconds,
            source_session_key=session_id,
            channel=channel,
            chat_id=chat_id,
        )
        return self._serialize_task(task)

    def delete_task(self, task_id: str) -> bool:
        """删除一条任务。"""
        return self.agent_loop.tasks.delete_task(task_id)

    def enable_task(self, task_id: str) -> dict | None:
        """启用一条任务。"""
        task = self.agent_loop.tasks.enable_task(task_id)
        return self._serialize_task(task) if task else None

    def disable_task(self, task_id: str) -> dict | None:
        """停用一条任务。"""
        task = self.agent_loop.tasks.disable_task(task_id)
        return self._serialize_task(task) if task else None

    def update_task_instruction(self, task_id: str, instruction: str) -> dict | None:
        """更新任务内容。"""
        task = self.agent_loop.tasks.update_instruction(task_id, instruction)
        return self._serialize_task(task) if task else None

    def reschedule_task_after(self, task_id: str, *, after_seconds: int) -> dict | None:
        """把任务改成延时执行。"""
        task = self.agent_loop.tasks.reschedule_after(task_id, after_seconds=after_seconds)
        return self._serialize_task(task) if task else None

    def reschedule_task_at(self, task_id: str, *, at: str) -> dict | None:
        """把任务改成定点执行。"""
        task = self.agent_loop.tasks.reschedule_at(task_id, at=at)
        return self._serialize_task(task) if task else None

    def reschedule_task_daily(self, task_id: str, *, daily_time: str) -> dict | None:
        """把任务改成每日执行。"""
        task = self.agent_loop.tasks.reschedule_daily(task_id, daily_time=daily_time)
        return self._serialize_task(task) if task else None

    def reschedule_task_every(self, task_id: str, *, every_seconds: int) -> dict | None:
        """把任务改成固定间隔执行。"""
        task = self.agent_loop.tasks.reschedule_every(task_id, every_seconds=every_seconds)
        return self._serialize_task(task) if task else None

    def list_skills(self) -> list[dict]:
        """列出当前已安装的 skills。"""
        items: list[dict] = []
        for skill in self.agent_loop.skill_registry.scan():
            items.append(
                {
                    "name": skill.metadata.name or skill.key,
                    "key": skill.key,
                    "path": str(skill.root),
                    "description": skill.metadata.description or "",
                }
            )
        return items

    def install_skill(self, source: str) -> tuple[bool, str]:
        """安装一个远端 skill。"""
        return SkillManager().install(source)

    def uninstall_skill(self, skill_name: str) -> tuple[bool, str]:
        """卸载一个远端 skill。"""
        return SkillManager().uninstall(skill_name)

    def list_mcp_servers(self) -> list[dict]:
        """列出当前 MCP servers。"""
        return self._build_sidebar_mcp_servers()

    async def create_mcp_server(self, mcp_name: str, payload: dict) -> dict:
        """创建一条 MCP 配置。"""
        if not mcp_name.strip():
            raise ValueError("mcp_name is required")
        config = load_config(get_config_path())
        if mcp_name in config.tools.mcp_servers:
            raise ValueError(f"MCP server already exists: {mcp_name}")
        config.tools.mcp_servers[mcp_name] = MCPServerConfig.model_validate(payload or {})
        await self._save_and_refresh_mcp_config(config)
        return self._serialize_mcp_server(mcp_name, config.tools.mcp_servers[mcp_name])

    async def update_mcp_server(self, mcp_name: str, payload: dict) -> dict:
        """更新一条 MCP 配置。"""
        config = load_config(get_config_path())
        current = config.tools.mcp_servers.get(mcp_name)
        if current is None:
            raise ValueError(f"MCP server not found: {mcp_name}")
        merged = current.model_dump(mode="json", by_alias=True)
        merged.update(payload or {})
        config.tools.mcp_servers[mcp_name] = MCPServerConfig.model_validate(merged)
        await self._save_and_refresh_mcp_config(config)
        return self._serialize_mcp_server(mcp_name, config.tools.mcp_servers[mcp_name])

    async def delete_mcp_server(self, mcp_name: str) -> bool:
        """删除一条 MCP 配置。"""
        config = load_config(get_config_path())
        if mcp_name not in config.tools.mcp_servers:
            return False
        config.tools.mcp_servers.pop(mcp_name, None)
        await self._save_and_refresh_mcp_config(config)
        return True

    async def enable_mcp_server(self, mcp_name: str) -> dict | None:
        """启用一条 MCP 配置。"""
        config = load_config(get_config_path())
        current = config.tools.mcp_servers.get(mcp_name)
        if current is None:
            return None
        current.enabled = True
        config.tools.mcp_servers[mcp_name] = current
        await self._save_and_refresh_mcp_config(config)
        return self._serialize_mcp_server(mcp_name, current)

    async def disable_mcp_server(self, mcp_name: str) -> dict | None:
        """停用一条 MCP 配置。"""
        config = load_config(get_config_path())
        current = config.tools.mcp_servers.get(mcp_name)
        if current is None:
            return None
        current.enabled = False
        config.tools.mcp_servers[mcp_name] = current
        await self._save_and_refresh_mcp_config(config)
        return self._serialize_mcp_server(mcp_name, current)

    async def clear_remote_runtime_state(self) -> None:
        """清理远端运行态，但保留配置和认证。"""
        runtime_root = get_data_dir()
        preserved = {"config.json", "weixin", "site-auth"}
        if runtime_root.exists():
            for path in runtime_root.iterdir():
                if path.name in preserved:
                    continue
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)

        self.agent_loop.sessions.clear_all()
        self.agent_loop.task_store.clear_all()
        self.agent_loop.cron_service.clear_all()

    async def start(self) -> None:
        """在后台启动 runtime 主循环。

        参数:
            无。

        返回:
            无返回值。
        """
        await self.lifecycle.start()

    async def wait(self) -> None:
        """等待后台主循环结束。

        参数:
            无。

        返回:
            无返回值。
        """
        await self.lifecycle.wait()

    def stop(self) -> None:
        """请求停止后台主循环。

        参数:
            无。

        返回:
            无返回值。
        """
        self.lifecycle.request_stop()

    async def close(self) -> None:
        """关闭 runtime 并释放外部资源。

        参数:
            无。

        返回:
            无返回值。
        """
        await self.lifecycle.close()

    @staticmethod
    def _serialize_session_summary(session: Session) -> dict:
        """把 session 转成对外可见的摘要。"""
        metadata = dict(session.metadata or {})
        title = metadata.get("title")
        if not isinstance(title, str) or not title.strip():
            title = None
        archived = bool(metadata.get("archived", False))
        return {
            "key": session.key,
            "session_id": session.key,
            "title": title,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "created_at_ms": int(session.created_at.timestamp() * 1000),
            "updated_at_ms": int(session.updated_at.timestamp() * 1000),
            "message_count": len(session.messages),
            "archived": archived,
            "source": str(metadata.get("source") or "remote"),
        }

    @staticmethod
    def _encode_session_page_token(*, updated_at_ms: int, session_id: str) -> str:
        """把分页游标编码成可传输字符串。"""
        payload = {"updated_at_ms": updated_at_ms, "session_id": session_id}
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_session_page_token(page_token: str | None) -> dict[str, object] | None:
        """解析分页游标。"""
        if page_token is None or not str(page_token).strip():
            return None
        raw = str(page_token).strip()
        padding = "=" * (-len(raw) % 4)
        try:
            decoded = base64.urlsafe_b64decode((raw + padding).encode("ascii"))
            payload = json.loads(decoded.decode("utf-8"))
        except Exception as exc:
            raise InvalidPageTokenError("invalid page token") from exc
        if not isinstance(payload, dict):
            raise InvalidPageTokenError("invalid page token")
        updated_at_ms = payload.get("updated_at_ms")
        session_id = payload.get("session_id")
        if not isinstance(updated_at_ms, int) or not isinstance(session_id, str) or not session_id:
            raise InvalidPageTokenError("invalid page token")
        return {"updated_at_ms": updated_at_ms, "session_id": session_id}

    @staticmethod
    def _is_session_after_cursor(item: dict, cursor: dict[str, object]) -> bool:
        """判断某条会话是否排在游标之后。"""
        item_updated_at_ms = int(item.get("updated_at_ms") or 0)
        cursor_updated_at_ms = int(cursor.get("updated_at_ms") or 0)
        item_session_id = str(item.get("session_id") or item.get("key") or "")
        cursor_session_id = str(cursor.get("session_id") or "")
        if item_updated_at_ms < cursor_updated_at_ms:
            return True
        if item_updated_at_ms > cursor_updated_at_ms:
            return False
        return item_session_id > cursor_session_id

    @staticmethod
    def _split_session_id(session_id: str) -> tuple[str, str]:
        """把会话键拆成 channel 和 chat_id。"""
        if ":" in session_id:
            channel, chat_id = session_id.split(":", 1)
            return channel or "remote", chat_id or session_id
        return "remote", session_id

    @staticmethod
    def _normalize_session_messages_for_history(session: Session) -> list[dict]:
        """把 session 原始消息归一化为稳定可展示结构。"""
        normalized: list[dict] = []
        for message in session.messages:
            entry = {
                "role": message.get("role", ""),
                "content": message.get("content", ""),
            }
            if "timestamp" in message:
                entry["timestamp"] = message["timestamp"]
            for key in (
                "tool_calls",
                "tool_call_id",
                "name",
                "reasoning_content",
                "reasoning_items",
                "thinking_blocks",
            ):
                if key in message:
                    entry[key] = deepcopy(message[key])
            normalized.append(entry)

        start = 0
        for index, message in enumerate(normalized):
            if message.get("role") == "user":
                start = index
                break
        normalized = normalized[start:]
        return normalized

    def _build_sidebar_tasks(self) -> list[dict]:
        """构造远端任务侧栏数据。"""
        items: list[dict] = []
        for task in self.agent_loop.tasks.list_tasks(include_disabled=True):
            items.append(self._serialize_task(task))
        return items

    def _build_sidebar_skills(self) -> list[dict]:
        """构造远端 skill 侧栏数据。"""
        return [
            {
                "name": item["name"],
                "path": item["path"],
            }
            for item in self.list_skills()
        ]

    def _build_sidebar_mcp_servers(self) -> list[dict]:
        """构造远端 MCP 侧栏数据。"""
        config = load_config(get_config_path())
        items: list[dict] = []
        for name, server in sorted(config.tools.mcp_servers.items(), key=lambda item: item[0]):
            items.append(self._serialize_mcp_server(name, server))
        return items

    def _serialize_task(self, task) -> dict:
        """把任务对象转换成前端侧栏结构。"""
        return {
            "id": task.id,
            "title": task.title or task.id,
            "instruction": task.payload.instruction,
            "enabled": task.enabled,
            "scheduleKind": task.schedule.kind,
            "scheduleAtMs": task.schedule.at_ms,
            "scheduleEveryMs": task.schedule.every_ms,
            "scheduleExpr": task.schedule.expr,
            "scheduleTz": task.schedule.tz,
            "nextRunAtMs": self.agent_loop.tasks.next_run_for_task(task.id),
            "runCount": task.run.run_count,
            "status": task.run.status,
        }

    @staticmethod
    def _serialize_mcp_server(name: str, server: MCPServerConfig) -> dict:
        """把 MCP 配置转换成前端侧栏结构。"""
        transport = server.type or ("streamableHttp" if server.url else "stdio")
        return {
            "name": name,
            "enabled": server.enabled,
            "transport": transport,
            "command": server.command,
            "args": list(server.args),
            "url": server.url,
            "enabledTools": list(server.enabled_tools),
            "env": dict(server.env),
            "headers": dict(server.headers),
        }

    async def _save_and_refresh_mcp_config(self, config: Config) -> None:
        """保存 MCP 配置并刷新当前运行态连接。"""
        save_config(config, get_config_path())
        self.state.config = config
        await self.agent_loop.refresh_mcp_servers(config.tools.mcp_servers)
