"""自动任务核心数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from nomi.cron.types import CronSchedule

TaskExecutionType = Literal["scheduled", "prepared_delivery"]
TaskStatus = Literal["pending", "preparing", "prepared", "running", "delivered", "failed", "cancelled"]


@dataclass(slots=True)
class TaskPayload:
    """描述任务要让 agent 完成的内容。"""

    instruction: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskPayload":
        """从字典恢复任务内容。"""
        return cls(instruction=str(payload.get("instruction", "")))

    def to_dict(self) -> dict[str, Any]:
        """导出可持久化字典。"""
        return asdict(self)


@dataclass(slots=True)
class TaskRunState:
    """描述任务当前运行态。"""

    status: TaskStatus = "pending"
    run_count: int = 0
    last_run_at_ms: int | None = None
    prepared_result: str | None = None
    prepared_at_ms: int | None = None
    error: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskRunState":
        """从字典恢复运行态。"""
        return cls(
            status=payload.get("status", "pending"),
            run_count=int(payload.get("run_count", 0)),
            last_run_at_ms=payload.get("last_run_at_ms"),
            prepared_result=payload.get("prepared_result"),
            prepared_at_ms=payload.get("prepared_at_ms"),
            error=payload.get("error"),
        )

    def to_dict(self) -> dict[str, Any]:
        """导出可持久化字典。"""
        return asdict(self)


@dataclass(slots=True)
class Task:
    """描述一条完整任务定义。"""

    id: str
    title: str
    execution_type: TaskExecutionType
    enabled: bool
    payload: TaskPayload
    source_session_key: str
    target_channel: str
    target_chat_id: str
    schedule: CronSchedule
    turn: int | None = 1
    deliver_at_ms: int | None = None
    prepare_before_ms: int | None = None
    run: TaskRunState = field(default_factory=TaskRunState)
    created_at_ms: int = 0
    updated_at_ms: int = 0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Task":
        """从字典恢复任务对象。"""
        return cls(
            id=payload["id"],
            title=payload["title"],
            execution_type=payload.get("execution_type", "scheduled"),
            enabled=payload.get("enabled", True),
            payload=TaskPayload.from_dict(payload.get("payload", {})),
            source_session_key=payload.get("source_session_key", "cli:direct"),
            target_channel=payload.get("target_channel", "cli"),
            target_chat_id=payload.get("target_chat_id", "direct"),
            schedule=CronSchedule.from_dict(payload.get("schedule", {"kind": "at"})),
            turn=payload.get("turn"),
            deliver_at_ms=payload.get("deliver_at_ms"),
            prepare_before_ms=payload.get("prepare_before_ms"),
            run=TaskRunState.from_dict(payload.get("run", {})),
            created_at_ms=payload.get("created_at_ms", 0),
            updated_at_ms=payload.get("updated_at_ms", 0),
        )

    def to_dict(self) -> dict[str, Any]:
        """导出可持久化字典。"""
        return {
            "id": self.id,
            "title": self.title,
            "execution_type": self.execution_type,
            "enabled": self.enabled,
            "payload": self.payload.to_dict(),
            "source_session_key": self.source_session_key,
            "target_channel": self.target_channel,
            "target_chat_id": self.target_chat_id,
            "schedule": self.schedule.to_dict(),
            "turn": self.turn,
            "deliver_at_ms": self.deliver_at_ms,
            "prepare_before_ms": self.prepare_before_ms,
            "run": self.run.to_dict(),
            "created_at_ms": self.created_at_ms,
            "updated_at_ms": self.updated_at_ms,
        }
