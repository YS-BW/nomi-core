"""会话历史持久化。"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nomi.agent.execution.messages import find_legal_message_start
from nomi.session.errors import DuplicateSessionIdError, SessionNotFoundError
from nomi.utils.fs import ensure_dir, safe_filename


@dataclass
class Session:
    """一段会话的持久化模型。"""

    key: str  # `channel:chat_id` 形式的会话键
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # 已经归档到文件的消息条数

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """向会话追加一条消息。"""
        msg = {"role": role, "content": content, "timestamp": datetime.now().isoformat(), **kwargs}
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """返回适合送入模型的未归档消息历史。"""
        unconsolidated = self.messages[self.last_consolidated :]
        if max_messages <= 0:
            sliced = list(unconsolidated)
        else:
            sliced = unconsolidated[-max_messages:]

        # 优先从用户消息开始，避免把截断点落在半个轮次中间。
        for i, message in enumerate(sliced):
            if message.get("role") == "user":
                sliced = sliced[i:]
                break

        # 开头如果出现孤儿工具结果，需要剥掉以免污染上下文。
        start = find_legal_message_start(sliced)
        if start:
            sliced = sliced[start:]

        out: list[dict[str, Any]] = []
        for message in sliced:
            entry: dict[str, Any] = {"role": message["role"], "content": message.get("content", "")}
            for key in (
                "tool_calls",
                "tool_call_id",
                "name",
                "reasoning_content",
                "reasoning_items",
                "thinking_blocks",
            ):
                if key in message:
                    entry[key] = message[key]
            out.append(entry)
        return out

    def clear(self, *, clear_metadata: bool = False) -> None:
        """清空会话短期消息，并按需清理运行态附加状态。

        参数:
            clear_metadata: 是否同时清空 ``metadata`` 里的运行期附加状态。

        返回:
            无返回值。
        """
        self.messages = []
        self.last_consolidated = 0
        if clear_metadata:
            self.metadata = {}
        self.updated_at = datetime.now()

    def retain_recent_legal_suffix(self, max_messages: int) -> None:
        """保留一段合法的最近消息后缀。"""
        if max_messages <= 0:
            self.clear()
            return
        if len(self.messages) <= max_messages:
            return

        start_idx = max(0, len(self.messages) - max_messages)

        # 如果截断点落在轮次中间，需要回退到最近的用户消息。
        while start_idx > 0 and self.messages[start_idx].get("role") != "user":
            start_idx -= 1

        retained = self.messages[start_idx:]

        # 持久化后的尾部也要遵守和 get_history 一致的合法边界规则。
        start = find_legal_message_start(retained)
        if start:
            retained = retained[start:]

        dropped = len(self.messages) - len(retained)
        self.messages = retained
        self.last_consolidated = max(0, self.last_consolidated - dropped)
        self.updated_at = datetime.now()


class SessionManager:
    """管理会话加载、缓存与持久化。"""

    def __init__(self, workspace: Path):
        """初始化会话管理器。"""
        self.workspace = workspace
        self.sessions_dir = ensure_dir(self.workspace / "sessions")
        self._cache: dict[str, Session] = {}
        self._subscribers: dict[int, Callable[[str, Session, list[dict[str, Any]]], None]] = {}
        self._next_subscriber_id = 0

    def _get_session_path(self, key: str) -> Path:
        """Get the file path for a session."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"

    @staticmethod
    def _to_millis(value: datetime | None) -> int | None:
        """把 datetime 转成毫秒时间戳。"""
        if value is None:
            return None
        return int(value.timestamp() * 1000)

    @staticmethod
    def _derive_source(key: str, metadata: dict[str, Any]) -> str:
        """推导会话来源。"""
        source = metadata.get("source")
        if isinstance(source, str) and source.strip():
            return source.strip()
        if ":" in key:
            return key.split(":", 1)[0] or "remote"
        return "remote"

    def _load_summary(self, path: Path) -> dict[str, Any] | None:
        """读取单个会话的摘要信息。"""
        try:
            key: str | None = None
            with open(path, encoding="utf-8") as f:
                first_line = f.readline().strip()
                if first_line:
                    data = json.loads(first_line)
                    if data.get("_type") == "metadata":
                        key = str(data.get("key") or "").strip() or None
            if not key:
                key = path.stem.replace("_", ":", 1)

            session = self._load(key)
            if session is None:
                return None
            metadata = dict(session.metadata or {})
            created_at_ms = self._to_millis(session.created_at)
            updated_at_ms = self._to_millis(session.updated_at)
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
                "created_at_ms": created_at_ms,
                "updated_at_ms": updated_at_ms,
                "message_count": len(session.messages),
                "archived": archived,
                "source": self._derive_source(session.key, metadata),
                "path": str(path),
            }
        except Exception as exc:
            logger.warning("Failed to summarize session {}: {}", path, exc)
            return None

    def exists(self, key: str) -> bool:
        """判断会话是否存在。"""
        if key in self._cache:
            return True
        return self._get_session_path(key).exists()

    def get(self, key: str) -> Session | None:
        """读取现有会话，不存在时返回 ``None``。"""
        if key in self._cache:
            return self._cache[key]
        session = self._load(key)
        if session is not None:
            self._cache[key] = session
        return session

    def get_or_create(self, key: str) -> Session:
        """获取现有会话，必要时创建新会话。"""
        if key in self._cache:
            return self._cache[key]

        session = self._load(key)
        if session is None:
            session = Session(key=key)

        self._cache[key] = session
        return session

    def create_session(
        self,
        key: str | None = None,
        *,
        title: str | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """创建一条新的持久化会话。"""
        session_id = str(key or "").strip() or f"remote:{uuid.uuid4().hex}"
        path = self._get_session_path(session_id)
        if session_id in self._cache or path.exists():
            raise DuplicateSessionIdError("duplicate session id", session_id=session_id)

        session_metadata = dict(metadata or {})
        if title is not None:
            session_metadata["title"] = title
        session_metadata["source"] = str(source or session_metadata.get("source") or "remote")

        session = Session(
            key=session_id,
            metadata=session_metadata,
        )
        self.save(session)
        return session

    def delete_session(self, key: str) -> bool:
        """删除一条会话。"""
        path = self._get_session_path(key)
        if key not in self._cache and not path.exists():
            raise SessionNotFoundError("session not found", session_id=key)
        self._cache.pop(key, None)
        path.unlink(missing_ok=True)
        return True

    def _load(self, key: str) -> Session | None:
        """Load a session from disk."""
        path = self._get_session_path(key)
        if not path.exists():
            return None

        try:
            messages = []
            metadata = {}
            created_at = None
            updated_at = None
            last_consolidated = 0

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    data = json.loads(line)

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = (
                            datetime.fromisoformat(data["created_at"])
                            if data.get("created_at")
                            else None
                        )
                        updated_at = (
                            datetime.fromisoformat(data["updated_at"])
                            if data.get("updated_at")
                            else None
                        )
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                updated_at=updated_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated,
            )
        except Exception as e:
            logger.warning("Failed to load session {}: {}", key, e)
            return None

    def save(self, session: Session) -> None:
        """把会话写回磁盘。"""
        old_count = self._message_count_from_disk(session.key)
        path = self._get_session_path(session.key)

        with open(path, "w", encoding="utf-8") as f:
            metadata_line = {
                "_type": "metadata",
                "key": session.key,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
                "last_consolidated": session.last_consolidated,
            }
            f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
            for msg in session.messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        self._cache[session.key] = session
        self._notify_saved(session, old_count=old_count)

    def invalidate(self, key: str) -> None:
        """移除内存缓存中的会话。"""
        self._cache.pop(key, None)

    def subscribe_changes(
        self,
        callback: Callable[[str, Session, list[dict[str, Any]]], None],
    ) -> Callable[[], None]:
        """订阅 session 持久化变更。"""
        subscriber_id = self._next_subscriber_id
        self._next_subscriber_id += 1
        self._subscribers[subscriber_id] = callback

        def _unsubscribe() -> None:
            self._subscribers.pop(subscriber_id, None)

        return _unsubscribe

    def _message_count_from_disk(self, key: str) -> int:
        """返回磁盘上已有消息条数。"""
        cached = self._cache.get(key)
        path = self._get_session_path(key)
        if not path.exists():
            return 0
        loaded = self._load(key)
        if cached is not None:
            self._cache[key] = cached
        return len(loaded.messages) if loaded is not None else 0

    def _notify_saved(self, session: Session, *, old_count: int) -> None:
        """通知订阅者 session 已保存。"""
        new_messages = [dict(item) for item in session.messages[old_count:]]
        for callback in list(self._subscribers.values()):
            try:
                callback("saved", session, new_messages)
            except Exception:
                continue

    def list_sessions(self) -> list[dict[str, Any]]:
        """列出所有已持久化会话。"""
        sessions = []

        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                summary = self._load_summary(path)
                if summary is not None:
                    sessions.append(summary)
            except Exception:
                continue

        return sorted(
            sessions,
            key=lambda x: (
                -(int(x.get("updated_at_ms") or 0)),
                str(x.get("session_id") or x.get("key") or ""),
            ),
        )

    def clear_all(self) -> None:
        """清空全部会话缓存与持久化文件。"""
        self._cache = {}
        if not self.sessions_dir.exists():
            return
        for path in self.sessions_dir.glob("*.jsonl"):
            path.unlink(missing_ok=True)
