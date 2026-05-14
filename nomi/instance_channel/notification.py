"""实例级全局通知出口。"""

from __future__ import annotations

from nomi.tasks import TaskRunner


class NotificationService:
    """把系统通知投递到当前实例已挂载渠道。"""

    def __init__(self, task_runner: TaskRunner) -> None:
        """绑定当前 runtime 的任务投递队列。"""
        self._tasks = task_runner

    def enqueue_global(self, *, notification_id: str, content: str) -> bool:
        """写入一条实例级全局通知。"""
        return self._tasks.enqueue_global_reminder(
            task_id=notification_id,
            session_id="instance:notifications",
            content=content,
            target_channels=[],
        )
