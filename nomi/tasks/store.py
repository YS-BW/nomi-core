"""自动任务持久化 owner。"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from loguru import logger

from nomi.tasks.models import Task


def _now_ms() -> int:
    """返回当前毫秒时间戳。"""
    return int(time.time() * 1000)


class TaskStore:
    """负责任务定义的读写与查询。"""

    def __init__(self, store_path: Path) -> None:
        """初始化任务存储。"""
        self.store_path = store_path
        self._tasks: list[Task] = []

    def _load_tasks(self) -> list[Task]:
        """从磁盘读取任务列表。"""
        if not self.store_path.exists():
            return []
        try:
            payload = json.loads(self.store_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning("Failed to decode task store {}: {}", self.store_path, exc)
            return []
        return [Task.from_dict(item) for item in payload.get("tasks", [])]

    def _save_tasks(self) -> None:
        """把任务列表写回磁盘。"""
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "tasks": [task.to_dict() for task in self._tasks],
        }
        self.store_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _ensure_loaded(self) -> None:
        """按需加载任务列表。"""
        if not self._tasks:
            self._tasks = self._load_tasks()

    def list_tasks(self, include_disabled: bool = False) -> list[Task]:
        """列出当前任务。"""
        self._ensure_loaded()
        tasks = self._tasks if include_disabled else [task for task in self._tasks if task.enabled]
        return sorted(tasks, key=lambda item: item.created_at_ms)

    def get_task(self, task_id: str) -> Task | None:
        """按 ID 查找任务。"""
        self._ensure_loaded()
        return next((task for task in self._tasks if task.id == task_id), None)

    def create_task(self, task: Task) -> Task:
        """保存一条新任务。"""
        self._ensure_loaded()
        now_ms = _now_ms()
        if not task.id:
            task.id = f"task_{uuid.uuid4().hex[:12]}"
        task.created_at_ms = now_ms
        task.updated_at_ms = now_ms
        self._tasks.append(task)
        self._save_tasks()
        return task

    def update_task(self, task: Task) -> Task:
        """写回一条已存在任务。"""
        self._ensure_loaded()
        task.updated_at_ms = _now_ms()
        for index, existing in enumerate(self._tasks):
            if existing.id == task.id:
                self._tasks[index] = task
                self._save_tasks()
                return task
        self._tasks.append(task)
        self._save_tasks()
        return task

    def remove_task(self, task_id: str) -> bool:
        """删除一条任务。"""
        self._ensure_loaded()
        before = len(self._tasks)
        self._tasks = [task for task in self._tasks if task.id != task_id]
        changed = len(self._tasks) != before
        if changed:
            self._save_tasks()
        return changed

    def clear_all(self) -> None:
        """清空全部任务定义。"""
        self._tasks = []
        if self.store_path.exists():
            self.store_path.unlink()
