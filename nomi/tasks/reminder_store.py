"""实例级全局提醒投递存储。"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import fcntl


def _now_ms() -> int:
    """返回当前毫秒时间戳。"""
    return int(time.time() * 1000)


@dataclass(slots=True)
class ReminderDelivery:
    """描述一条实例级全局提醒投递记录。"""

    id: str
    task_id: str
    session_id: str
    content: str
    targets: list[str]
    delivered_to: list[str] = field(default_factory=list)
    created_at_ms: int = 0
    updated_at_ms: int = 0

    @classmethod
    def from_dict(cls, payload: dict) -> "ReminderDelivery":
        """从字典恢复提醒投递记录。"""
        return cls(
            id=str(payload.get("id") or ""),
            task_id=str(payload.get("task_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            content=str(payload.get("content") or ""),
            targets=[str(item) for item in payload.get("targets") or [] if str(item).strip()],
            delivered_to=[
                str(item)
                for item in payload.get("delivered_to") or []
                if str(item).strip()
            ],
            created_at_ms=int(payload.get("created_at_ms") or 0),
            updated_at_ms=int(payload.get("updated_at_ms") or 0),
        )

    def to_dict(self) -> dict:
        """导出可持久化字典。"""
        return asdict(self)


class ReminderStore:
    """维护实例级全局提醒队列。"""

    def __init__(self, store_path: Path) -> None:
        """初始化提醒存储。"""
        self.store_path = store_path
        self._lock_path = store_path.with_suffix(".lock")

    def enqueue(
        self,
        *,
        task_id: str,
        session_id: str,
        content: str,
        targets: list[str],
    ) -> ReminderDelivery | None:
        """追加一条新的全局提醒。"""
        normalized_targets = sorted({str(item).strip() for item in targets if str(item).strip()})
        if not normalized_targets:
            return None
        now_ms = _now_ms()
        delivery = ReminderDelivery(
            id=f"reminder_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            session_id=session_id,
            content=str(content or "").strip(),
            targets=normalized_targets,
            delivered_to=[],
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
        )

        def _mutate(items: list[ReminderDelivery]) -> list[ReminderDelivery]:
            items.append(delivery)
            return self._prune(items)

        self._update(_mutate)
        return delivery

    def list_pending(self, consumer: str) -> list[ReminderDelivery]:
        """列出某个 consumer 尚未投递的提醒。"""
        normalized_consumer = str(consumer or "").strip()
        if not normalized_consumer:
            return []
        deliveries = self._read_all()
        return [
            item
            for item in deliveries
            if normalized_consumer in item.targets and normalized_consumer not in item.delivered_to
        ]

    def mark_delivered(self, delivery_id: str, consumer: str) -> bool:
        """标记某个 consumer 已完成投递。"""
        normalized_consumer = str(consumer or "").strip()
        if not normalized_consumer:
            return False
        changed = False

        def _mutate(items: list[ReminderDelivery]) -> list[ReminderDelivery]:
            nonlocal changed
            for item in items:
                if item.id != delivery_id:
                    continue
                if normalized_consumer in item.delivered_to:
                    return self._prune(items)
                item.delivered_to.append(normalized_consumer)
                item.delivered_to = sorted(set(item.delivered_to))
                item.updated_at_ms = _now_ms()
                changed = True
                break
            return self._prune(items)

        self._update(_mutate)
        return changed

    def _read_all(self) -> list[ReminderDelivery]:
        """读取全部提醒记录。"""
        if not self.store_path.exists():
            return []
        try:
            payload = json.loads(self.store_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return [
            ReminderDelivery.from_dict(item)
            for item in payload.get("deliveries") or []
            if isinstance(item, dict)
        ]

    def _write_all(self, deliveries: list[ReminderDelivery]) -> None:
        """写回全部提醒记录。"""
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "deliveries": [item.to_dict() for item in deliveries],
        }
        self.store_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _update(self, mutate) -> None:
        """在文件锁保护下更新提醒记录。"""
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            deliveries = self._read_all()
            deliveries = mutate(deliveries)
            self._write_all(deliveries)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _prune(items: list[ReminderDelivery]) -> list[ReminderDelivery]:
        """清理过旧且已完成投递的提醒。"""
        if len(items) <= 200:
            return items
        kept: list[ReminderDelivery] = []
        completed: list[ReminderDelivery] = []
        for item in items:
            if sorted(set(item.targets)) == sorted(set(item.delivered_to)):
                completed.append(item)
            else:
                kept.append(item)
        completed = sorted(completed, key=lambda item: item.updated_at_ms)
        while len(kept) + len(completed) > 200 and completed:
            completed.pop(0)
        return kept + completed
