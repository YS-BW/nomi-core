"""单轮执行期的 Turn Journal 持久化与恢复。"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from nomi.session.manager import Session
from nomi.utils.fs import ensure_dir, safe_filename

_JOURNAL_VERSION = 1
_TURN_JOURNAL_KEY = "turn_journal"
_PREVIOUS_INTERRUPTED_KEY = "previous_turn_interrupted"


@dataclass(slots=True)
class ToolJournalEntry:
    """描述单个工具调用在当前轮中的状态。"""

    tool_call_id: str
    name: str
    arguments: dict[str, Any]
    status: str
    result: Any | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为可持久化字典。"""
        return {
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "arguments": self.arguments,
            "status": self.status,
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ToolJournalEntry":
        """从字典反序列化工具状态。"""
        return cls(
            tool_call_id=str(payload.get("tool_call_id") or ""),
            name=str(payload.get("name") or "tool"),
            arguments=dict(payload.get("arguments") or {}),
            status=str(payload.get("status") or "planned"),
            result=payload.get("result"),
            error=payload.get("error"),
        )


@dataclass(slots=True)
class TurnJournalRecord:
    """承载一轮消息执行中的完整可恢复状态。"""

    turn_id: str
    session_key: str
    status: str = "running"
    user_message: dict[str, Any] | None = None
    visible_assistant_text: str = ""
    assistant_message: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_entries: list[ToolJournalEntry] = field(default_factory=list)
    interrupt_reason: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def touch(self) -> None:
        """刷新更新时间。"""
        self.updated_at = datetime.now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        """转换为可持久化字典。"""
        return {
            "version": _JOURNAL_VERSION,
            "turn_id": self.turn_id,
            "session_key": self.session_key,
            "status": self.status,
            "user_message": self.user_message,
            "visible_assistant_text": self.visible_assistant_text,
            "assistant_message": self.assistant_message,
            "tool_calls": self.tool_calls,
            "tool_entries": [entry.to_dict() for entry in self.tool_entries],
            "interrupt_reason": self.interrupt_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TurnJournalRecord":
        """从字典反序列化 journal。"""
        return cls(
            turn_id=str(payload.get("turn_id") or ""),
            session_key=str(payload.get("session_key") or ""),
            status=str(payload.get("status") or "running"),
            user_message=payload.get("user_message"),
            visible_assistant_text=str(payload.get("visible_assistant_text") or ""),
            assistant_message=payload.get("assistant_message"),
            tool_calls=list(payload.get("tool_calls") or []),
            tool_entries=[
                ToolJournalEntry.from_dict(item)
                for item in list(payload.get("tool_entries") or [])
                if isinstance(item, dict)
            ],
            interrupt_reason=payload.get("interrupt_reason"),
            created_at=str(payload.get("created_at") or datetime.now().isoformat()),
            updated_at=str(payload.get("updated_at") or datetime.now().isoformat()),
        )


class TurnJournalStore:
    """负责 turn journal 的落盘、读取与清理。"""

    def __init__(self, workspace: Path) -> None:
        """绑定 workspace 下的 journal 目录。"""
        self._dir = ensure_dir(workspace / "run_logs" / "turn_journals")

    def _path_for(self, session_key: str, turn_id: str) -> Path:
        safe_session = safe_filename(session_key.replace(":", "_"))
        safe_turn = safe_filename(turn_id)
        return self._dir / f"{safe_session}__{safe_turn}.json"

    def create(self, session_key: str) -> TurnJournalRecord:
        """创建一份新的运行中 journal。"""
        turn_id = f"turn_{uuid.uuid4().hex[:12]}"
        record = TurnJournalRecord(turn_id=turn_id, session_key=session_key)
        self.save(record)
        return record

    def save(self, record: TurnJournalRecord) -> None:
        """写回当前 journal。"""
        record.touch()
        path = self._path_for(record.session_key, record.turn_id)
        path.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def delete(self, session_key: str, turn_id: str) -> None:
        """删除指定 journal 文件。"""
        path = self._path_for(session_key, turn_id)
        if path.exists():
            path.unlink()

    def load(self, session_key: str, turn_id: str) -> TurnJournalRecord | None:
        """读取一份已有 journal。"""
        path = self._path_for(session_key, turn_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return None
            return TurnJournalRecord.from_dict(payload)
        except Exception:
            return None

    def maybe_load_from_session(self, session: Session) -> TurnJournalRecord | None:
        """根据 session metadata 读取当前挂起的 journal。"""
        meta = session.metadata.get(_TURN_JOURNAL_KEY)
        if not isinstance(meta, dict):
            return None
        turn_id = str(meta.get("turn_id") or "")
        session_key = str(meta.get("session_key") or session.key)
        if not turn_id:
            return None
        return self.load(session_key, turn_id)


def attach_running_journal_metadata(session: Session, record: TurnJournalRecord) -> None:
    """在 session metadata 上登记当前运行中的 journal。"""
    session.metadata[_TURN_JOURNAL_KEY] = {
        "turn_id": record.turn_id,
        "session_key": record.session_key,
        "status": record.status,
    }


def clear_running_journal_metadata(session: Session) -> None:
    """移除运行中的 journal metadata。"""
    session.metadata.pop(_TURN_JOURNAL_KEY, None)


def set_previous_interrupted_metadata(
    session: Session,
    *,
    turn_id: str,
    reason: str | None,
) -> None:
    """登记上一轮被中断的短期元信息。"""
    session.metadata[_PREVIOUS_INTERRUPTED_KEY] = {
        "turn_id": turn_id,
        "interrupt_reason": reason,
        "active": True,
    }


def consume_previous_interrupted_metadata(session: Session) -> dict[str, Any] | None:
    """消费并清理上一轮中断元信息。"""
    payload = session.metadata.pop(_PREVIOUS_INTERRUPTED_KEY, None)
    if isinstance(payload, dict):
        return payload
    return None
