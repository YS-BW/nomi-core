"""自动任务工具。"""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime
from typing import Any

from nomi.agent.tools.base import Tool, tool_parameters
from nomi.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema
from nomi.tasks import TaskRunner


class _BaseTaskTool(Tool):
    """封装任务工具共享逻辑。"""

    def __init__(self, task_runner: TaskRunner, default_timezone: str = "Asia/Shanghai") -> None:
        """初始化共享任务工具状态。"""
        self._tasks = task_runner
        self._default_timezone = default_timezone

    @staticmethod
    def _normalize_instruction(instruction: str | None) -> str | None:
        """去除首尾空白并拦截空指令。"""
        if instruction is None:
            return None
        normalized = instruction.strip()
        if not normalized:
            return None
        return normalized

    @staticmethod
    def _reject_unexpected_kwargs(kwargs: dict[str, Any]) -> str | None:
        """拒绝当前协议之外的额外参数。"""
        if not kwargs:
            return None
        unexpected = ", ".join(sorted(kwargs))
        return f"Error: unexpected parameters: {unexpected}"

    def _format_timestamp(self, ms: int | None) -> str:
        """把毫秒时间戳格式化成人类可读文本。"""
        if ms is None:
            return "-"
        from zoneinfo import ZoneInfo

        dt = datetime.fromtimestamp(ms / 1000, tz=ZoneInfo(self._default_timezone))
        return f"{dt.isoformat()} ({self._default_timezone})"

    def _format_schedule_kind(self, task) -> str:
        """格式化任务的时间语义。"""
        schedule = task.schedule
        if schedule.kind == "at":
            return "after" if task.turn == 1 and task.run.run_count == 0 else "at"
        if schedule.kind == "every":
            return "every"
        if schedule.kind == "cron":
            return "daily"
        return schedule.kind

    def _format_task(self, task) -> str:
        """格式化单个任务详情。"""
        lines = [
            f"task_id: {task.id}",
            f"enabled: {task.enabled}",
            f"instruction: {task.payload.instruction}",
            f"schedule kind: {self._format_schedule_kind(task)}",
            f"next run: {self._format_timestamp(self._tasks.next_run_for_task(task.id))}",
            f"run_count: {task.run.run_count}",
        ]
        return "\n".join(lines)

    def _format_list(self, include_disabled: bool = False) -> str:
        """格式化任务列表。"""
        tasks = self._tasks.list_tasks(include_disabled=include_disabled)
        if not tasks:
            return "当前没有自动任务。"

        lines = [f"当前有 {len(tasks)} 个自动任务：", ""]
        for task in tasks:
            lines.append(self._format_task(task))
            lines.append("")
        return "\n".join(lines).rstrip()


class _TaskContextTool(_BaseTaskTool):
    """封装需要会话上下文的任务工具。"""

    def __init__(self, task_runner: TaskRunner, default_timezone: str = "Asia/Shanghai") -> None:
        """初始化上下文相关状态。"""
        super().__init__(task_runner, default_timezone=default_timezone)
        self._channel = "cli"
        self._chat_id = "direct"
        self._session_key = "cli:direct"
        self._task_context: ContextVar[bool] = ContextVar("task_context", default=False)

    def set_context(
        self,
        channel: str,
        chat_id: str,
        message_id: str | None = None,
        session_key: str | None = None,
    ) -> None:
        """记录当前会话上下文，供创建任务时复用。"""
        del message_id
        self._channel = channel
        self._chat_id = chat_id
        self._session_key = session_key or f"{channel}:{chat_id}"

    def set_task_context(self, active: bool):
        """标记当前是否处于任务执行内部。"""
        return self._task_context.set(active)

    def reset_task_context(self, token) -> None:
        """恢复之前的任务上下文标记。"""
        self._task_context.reset(token)

    def _ensure_not_in_task_context(self) -> str | None:
        """阻止任务内部递归创建新任务。"""
        if self._task_context.get():
            return "Error: cannot create a new task from inside a running task."
        return None


@tool_parameters(
    tool_parameters_schema(
        instruction=StringSchema("到点后要发给用户的话"),
        after_seconds=IntegerSchema(
            description="距离现在多少秒后触发",
            minimum=1,
        ),
        required=["instruction", "after_seconds"],
    )
)
class TaskCreateAfterTool(_TaskContextTool):
    """创建一次性延时任务。"""

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "task_create_after"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return "Create a one-shot delayed task after some seconds."

    async def execute(
        self,
        *,
        instruction: str,
        after_seconds: int,
        **kwargs: Any,
    ) -> str:
        """创建一条一次性延时任务。"""
        if error := self._reject_unexpected_kwargs(kwargs):
            return error
        if error := self._ensure_not_in_task_context():
            return error
        normalized = self._normalize_instruction(instruction)
        if normalized is None:
            return "Error: instruction is required"
        try:
            task = self._tasks.create_after_task(
                instruction=normalized,
                after_seconds=after_seconds,
                source_session_key=self._session_key,
                channel=self._channel,
                chat_id=self._chat_id,
            )
        except ValueError as exc:
            return f"Error: {exc}"
        return f"已创建自动任务：`{task.id}`（{task.title}）"


@tool_parameters(
    tool_parameters_schema(
        instruction=StringSchema("到点后要发给用户的话"),
        at=StringSchema("ISO 8601 本地时间字符串"),
        required=["instruction", "at"],
    )
)
class TaskCreateAtTool(_TaskContextTool):
    """创建一次性定点任务。"""

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "task_create_at"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return "Create a one-shot task at a specific local ISO datetime."

    async def execute(
        self,
        *,
        instruction: str,
        at: str,
        **kwargs: Any,
    ) -> str:
        """创建一条一次性定点任务。"""
        if error := self._reject_unexpected_kwargs(kwargs):
            return error
        if error := self._ensure_not_in_task_context():
            return error
        normalized = self._normalize_instruction(instruction)
        if normalized is None:
            return "Error: instruction is required"
        try:
            task = self._tasks.create_at_task(
                instruction=normalized,
                at=at,
                source_session_key=self._session_key,
                channel=self._channel,
                chat_id=self._chat_id,
            )
        except ValueError as exc:
            return f"Error: {exc}"
        return f"已创建自动任务：`{task.id}`（{task.title}）"


@tool_parameters(
    tool_parameters_schema(
        instruction=StringSchema("到点后要发给用户的话"),
        daily_time=StringSchema("每天触发时间，格式 HH:MM"),
        required=["instruction", "daily_time"],
    )
)
class TaskCreateDailyTool(_TaskContextTool):
    """创建每天固定时间重复任务。"""

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "task_create_daily"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return "Create a daily repeating task at HH:MM."

    async def execute(
        self,
        *,
        instruction: str,
        daily_time: str,
        **kwargs: Any,
    ) -> str:
        """创建一条每天固定时间重复任务。"""
        if error := self._reject_unexpected_kwargs(kwargs):
            return error
        if error := self._ensure_not_in_task_context():
            return error
        normalized = self._normalize_instruction(instruction)
        if normalized is None:
            return "Error: instruction is required"
        try:
            task = self._tasks.create_daily_task(
                instruction=normalized,
                daily_time=daily_time,
                source_session_key=self._session_key,
                channel=self._channel,
                chat_id=self._chat_id,
            )
        except ValueError as exc:
            return f"Error: {exc}"
        return f"已创建自动任务：`{task.id}`（{task.title}）"


@tool_parameters(
    tool_parameters_schema(
        instruction=StringSchema("到点后要发给用户的话"),
        every_seconds=IntegerSchema(
            description="每隔多少秒执行一次",
            minimum=1,
        ),
        required=["instruction", "every_seconds"],
    )
)
class TaskCreateEveryTool(_TaskContextTool):
    """创建固定间隔重复任务。"""

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "task_create_every"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return "Create an interval-based repeating task."

    async def execute(
        self,
        *,
        instruction: str,
        every_seconds: int,
        **kwargs: Any,
    ) -> str:
        """创建一条固定间隔重复任务。"""
        if error := self._reject_unexpected_kwargs(kwargs):
            return error
        if error := self._ensure_not_in_task_context():
            return error
        normalized = self._normalize_instruction(instruction)
        if normalized is None:
            return "Error: instruction is required"
        try:
            task = self._tasks.create_every_task(
                instruction=normalized,
                every_seconds=every_seconds,
                source_session_key=self._session_key,
                channel=self._channel,
                chat_id=self._chat_id,
            )
        except ValueError as exc:
            return f"Error: {exc}"
        return f"已创建自动任务：`{task.id}`（{task.title}）"


@tool_parameters(tool_parameters_schema())
class TaskListTool(_BaseTaskTool):
    """列出当前任务。"""

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "task_list"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return "List the current automatic tasks."

    @property
    def read_only(self) -> bool:
        """声明该工具是只读工具。"""
        return True

    async def execute(self, **kwargs: Any) -> str:
        """列出任务。"""
        if error := self._reject_unexpected_kwargs(kwargs):
            return error
        return self._format_list(include_disabled=True)


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema("任务 ID"),
        required=["task_id"],
    )
)
class TaskGetTool(_BaseTaskTool):
    """查看单个任务详情。"""

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "task_get"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return "Get details of one automatic task by task_id."

    @property
    def read_only(self) -> bool:
        """声明该工具是只读工具。"""
        return True

    async def execute(self, *, task_id: str | None = None, **kwargs: Any) -> str:
        """查看单个任务详情。"""
        if error := self._reject_unexpected_kwargs(kwargs):
            return error
        if not task_id:
            return "Error: task_id is required"
        task = self._tasks.get_task(task_id)
        if task is None:
            return f"Error: 自动任务 `{task_id}` 不存在"
        return self._format_task(task)


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema("要删除的任务 ID"),
        required=["task_id"],
    )
)
class TaskDeleteTool(_BaseTaskTool):
    """删除指定任务。"""

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "task_delete"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return "Delete an automatic task by task_id."

    async def execute(self, *, task_id: str | None = None, **kwargs: Any) -> str:
        """删除任务。"""
        if error := self._reject_unexpected_kwargs(kwargs):
            return error
        if not task_id:
            return "Error: task_id is required"
        if self._tasks.delete_task(task_id):
            return f"已删除自动任务：`{task_id}`"
        return f"Error: 自动任务 `{task_id}` 不存在"


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema("要启用的任务 ID"),
        required=["task_id"],
    )
)
class TaskEnableTool(_BaseTaskTool):
    """启用指定任务。"""

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "task_enable"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return "Enable an automatic task by task_id."

    async def execute(self, *, task_id: str | None = None, **kwargs: Any) -> str:
        """启用任务。"""
        if error := self._reject_unexpected_kwargs(kwargs):
            return error
        if not task_id:
            return "Error: task_id is required"
        task = self._tasks.enable_task(task_id)
        if task is None:
            return f"Error: 自动任务 `{task_id}` 不存在"
        return f"已启用自动任务：`{task.id}`（{task.title}）"


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema("要停用的任务 ID"),
        required=["task_id"],
    )
)
class TaskDisableTool(_BaseTaskTool):
    """停用指定任务。"""

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "task_disable"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return "Disable an automatic task by task_id."

    async def execute(self, *, task_id: str | None = None, **kwargs: Any) -> str:
        """停用任务。"""
        if error := self._reject_unexpected_kwargs(kwargs):
            return error
        if not task_id:
            return "Error: task_id is required"
        task = self._tasks.disable_task(task_id)
        if task is None:
            return f"Error: 自动任务 `{task_id}` 不存在"
        return f"已停用自动任务：`{task.id}`（{task.title}）"


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema("要更新的任务 ID"),
        instruction=StringSchema("新的任务内容"),
        required=["task_id", "instruction"],
    )
)
class TaskUpdateInstructionTool(_BaseTaskTool):
    """更新任务内容。"""

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "task_update_instruction"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return "Update only the instruction of an automatic task."

    async def execute(
        self,
        *,
        task_id: str | None = None,
        instruction: str | None = None,
        **kwargs: Any,
    ) -> str:
        """更新任务内容。"""
        if error := self._reject_unexpected_kwargs(kwargs):
            return error
        if not task_id:
            return "Error: task_id is required"
        normalized = self._normalize_instruction(instruction)
        if normalized is None:
            return "Error: instruction is required"
        task = self._tasks.update_instruction(task_id, normalized)
        if task is None:
            return f"Error: 自动任务 `{task_id}` 不存在"
        return f"已更新自动任务：`{task.id}`（{task.title}）"


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema("要重排程的任务 ID"),
        after_seconds=IntegerSchema(
            description="距离现在多少秒后触发",
            minimum=1,
        ),
        required=["task_id", "after_seconds"],
    )
)
class TaskRescheduleAfterTool(_BaseTaskTool):
    """把任务改成一次性延时执行。"""

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "task_reschedule_after"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return "Reschedule a task to run once after some seconds."

    async def execute(
        self,
        *,
        task_id: str | None = None,
        after_seconds: int | None = None,
        **kwargs: Any,
    ) -> str:
        """把任务改成一次性延时执行。"""
        if error := self._reject_unexpected_kwargs(kwargs):
            return error
        if not task_id:
            return "Error: task_id is required"
        if after_seconds is None:
            return "Error: after_seconds is required"
        try:
            task = self._tasks.reschedule_after(task_id, after_seconds=after_seconds)
        except ValueError as exc:
            return f"Error: {exc}"
        if task is None:
            return f"Error: 自动任务 `{task_id}` 不存在"
        return f"已更新自动任务：`{task.id}`（{task.title}）"


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema("要重排程的任务 ID"),
        at=StringSchema("ISO 8601 本地时间字符串"),
        required=["task_id", "at"],
    )
)
class TaskRescheduleAtTool(_BaseTaskTool):
    """把任务改成一次性定点执行。"""

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "task_reschedule_at"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return "Reschedule a task to run once at a specific local ISO datetime."

    async def execute(
        self,
        *,
        task_id: str | None = None,
        at: str | None = None,
        **kwargs: Any,
    ) -> str:
        """把任务改成一次性定点执行。"""
        if error := self._reject_unexpected_kwargs(kwargs):
            return error
        if not task_id:
            return "Error: task_id is required"
        if not at:
            return "Error: at is required"
        try:
            task = self._tasks.reschedule_at(task_id, at=at)
        except ValueError as exc:
            return f"Error: {exc}"
        if task is None:
            return f"Error: 自动任务 `{task_id}` 不存在"
        return f"已更新自动任务：`{task.id}`（{task.title}）"


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema("要重排程的任务 ID"),
        daily_time=StringSchema("每天触发时间，格式 HH:MM"),
        required=["task_id", "daily_time"],
    )
)
class TaskRescheduleDailyTool(_BaseTaskTool):
    """把任务改成每天固定时间执行。"""

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "task_reschedule_daily"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return "Reschedule a task to run daily at HH:MM."

    async def execute(
        self,
        *,
        task_id: str | None = None,
        daily_time: str | None = None,
        **kwargs: Any,
    ) -> str:
        """把任务改成每天固定时间执行。"""
        if error := self._reject_unexpected_kwargs(kwargs):
            return error
        if not task_id:
            return "Error: task_id is required"
        if not daily_time:
            return "Error: daily_time is required"
        try:
            task = self._tasks.reschedule_daily(task_id, daily_time=daily_time)
        except ValueError as exc:
            return f"Error: {exc}"
        if task is None:
            return f"Error: 自动任务 `{task_id}` 不存在"
        return f"已更新自动任务：`{task.id}`（{task.title}）"


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema("要重排程的任务 ID"),
        every_seconds=IntegerSchema(
            description="每隔多少秒执行一次",
            minimum=1,
        ),
        required=["task_id", "every_seconds"],
    )
)
class TaskRescheduleEveryTool(_BaseTaskTool):
    """把任务改成固定间隔执行。"""

    @property
    def name(self) -> str:
        """返回工具名称。"""
        return "task_reschedule_every"

    @property
    def description(self) -> str:
        """返回工具描述。"""
        return "Reschedule a task to run repeatedly every N seconds."

    async def execute(
        self,
        *,
        task_id: str | None = None,
        every_seconds: int | None = None,
        **kwargs: Any,
    ) -> str:
        """把任务改成固定间隔执行。"""
        if error := self._reject_unexpected_kwargs(kwargs):
            return error
        if not task_id:
            return "Error: task_id is required"
        if every_seconds is None:
            return "Error: every_seconds is required"
        try:
            task = self._tasks.reschedule_every(task_id, every_seconds=every_seconds)
        except ValueError as exc:
            return f"Error: {exc}"
        if task is None:
            return f"Error: 自动任务 `{task_id}` 不存在"
        return f"已更新自动任务：`{task.id}`（{task.title}）"
