"""自动任务 orchestrator。"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

from loguru import logger

from nomi.cron import CronJob, CronSchedule, CronService
from nomi.tasks.delivery import TaskDelivery
from nomi.tasks.models import Task, TaskPayload
from nomi.tasks.store import TaskStore

if TYPE_CHECKING:
    from nomi.agent.loop import AgentLoop

TaskPhase = Literal["run", "prepare", "deliver"]


def _now_ms() -> int:
    """返回当前毫秒时间戳。"""
    return int(time.time() * 1000)


class TaskRunner:
    """统一管理任务定义、调度与执行。"""

    DEFAULT_PREPARE_BEFORE_MS = 10 * 60 * 1000

    def __init__(self, loop: "AgentLoop", store: TaskStore, cron_service: CronService) -> None:
        """初始化任务 orchestrator。"""
        self._loop = loop
        self._store = store
        self._cron = cron_service
        self._delivery = TaskDelivery(loop.bus)

    @property
    def store(self) -> TaskStore:
        """返回底层任务存储。"""
        return self._store

    def list_tasks(self, include_disabled: bool = False) -> list[Task]:
        """列出当前任务。"""
        return self._store.list_tasks(include_disabled=include_disabled)

    def get_task(self, task_id: str) -> Task | None:
        """按 ID 获取任务。"""
        return self._store.get_task(task_id)

    def _build_title(self, instruction: str) -> str:
        """按固定规则生成任务展示名。"""
        return instruction[:30].strip()

    def _format_daily_cron(self, daily_time: str) -> str:
        """把 HH:MM 转成 cron 表达式。"""
        try:
            hour_str, minute_str = daily_time.split(":", 1)
            hour = int(hour_str)
            minute = int(minute_str)
        except Exception as exc:
            raise ValueError("daily_time must look like HH:MM") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("daily_time must look like HH:MM")
        return f"{minute} {hour} * * *"

    def build_schedule(
        self,
        *,
        after_seconds: int | None = None,
        at: str | None = None,
        every_seconds: int | None = None,
        daily_time: str | None = None,
        cron_expr: str | None = None,
    ) -> CronSchedule:
        """把结构化时间参数转换成统一调度对象。"""
        provided = sum(
            1
            for value in (after_seconds, at, every_seconds, daily_time, cron_expr)
            if value not in (None, "")
        )
        if provided != 1:
            raise ValueError(
                "exactly one of after_seconds, at, every_seconds, daily_time, or cron_expr is required"
            )
        if after_seconds is not None:
            default_tz = self._loop.context.timezone or "Asia/Shanghai"
            from zoneinfo import ZoneInfo

            run_at = datetime.now(tz=ZoneInfo(default_tz)) + timedelta(seconds=after_seconds)
            return CronSchedule(kind="at", at_ms=int(run_at.timestamp() * 1000))
        if every_seconds is not None:
            return CronSchedule(kind="every", every_ms=every_seconds * 1000)
        if daily_time:
            return CronSchedule(
                kind="cron",
                expr=self._format_daily_cron(daily_time),
                tz=self._loop.context.timezone or "Asia/Shanghai",
            )
        if cron_expr:
            return CronSchedule(
                kind="cron",
                expr=cron_expr,
                tz=self._loop.context.timezone or "Asia/Shanghai",
            )
        try:
            run_at = datetime.fromisoformat(at or "")
        except ValueError as exc:
            raise ValueError(
                "invalid ISO datetime format. Expected e.g. 2026-04-29T09:30:00"
            ) from exc
        if run_at.tzinfo is None:
            from zoneinfo import ZoneInfo

            run_at = run_at.replace(tzinfo=ZoneInfo(self._loop.context.timezone or "Asia/Shanghai"))
        return CronSchedule(kind="at", at_ms=int(run_at.timestamp() * 1000))

    def _validate_turn(self, schedule: CronSchedule, turn: int | None) -> None:
        """校验执行次数和时间表达是否匹配。"""
        if turn is not None and turn <= 0:
            raise ValueError("turn must be >= 1 or null")
        if schedule.kind == "at" and turn not in (None, 1):
            raise ValueError("one-shot time only supports turn=1 or null")

    def _register_scheduled_jobs(self, task: Task) -> None:
        """为任务注册底层时间触发器。"""
        self._cron.remove_jobs_for_target("task", task.id)
        if task.execution_type == "scheduled":
            self._cron.add_job(
                name=task.title,
                schedule=task.schedule,
                target_kind="task",
                target_id=task.id,
                phase="run",
                delete_after_run=task.schedule.kind == "at",
            )
            return
        if task.schedule.kind != "at" or task.deliver_at_ms is None:
            raise ValueError("prepared_delivery currently requires a one-shot deliver time")
        prepare_before_ms = task.prepare_before_ms or self.DEFAULT_PREPARE_BEFORE_MS
        prepare_at_ms = task.deliver_at_ms - prepare_before_ms
        if prepare_at_ms <= _now_ms():
            raise ValueError("prepare time must still be in the future")
        self._cron.add_job(
            name=f"{task.title}:prepare",
            schedule=CronSchedule(kind="at", at_ms=prepare_at_ms),
            target_kind="task",
            target_id=task.id,
            phase="prepare",
            delete_after_run=True,
        )
        self._cron.add_job(
            name=f"{task.title}:deliver",
            schedule=CronSchedule(kind="at", at_ms=task.deliver_at_ms),
            target_kind="task",
            target_id=task.id,
            phase="deliver",
            delete_after_run=True,
        )

    def create_task(
        self,
        *,
        instruction: str,
        schedule: CronSchedule,
        turn: int | None,
        mode: Literal["scheduled", "prepared_delivery"] | None,
        source_session_key: str,
        channel: str,
        chat_id: str,
    ) -> Task:
        """创建并注册一条任务。"""
        normalized = instruction.strip()
        if not normalized:
            raise ValueError("instruction is required")
        execution_type = mode or "scheduled"
        self._validate_turn(schedule, turn)
        task = Task(
            id="",
            title=self._build_title(normalized),
            execution_type=execution_type,
            enabled=True,
            payload=TaskPayload(instruction=normalized),
            source_session_key=source_session_key,
            target_channel=channel,
            target_chat_id=chat_id,
            schedule=schedule,
            turn=turn,
            deliver_at_ms=schedule.at_ms if execution_type == "prepared_delivery" else None,
            prepare_before_ms=(
                self.DEFAULT_PREPARE_BEFORE_MS if execution_type == "prepared_delivery" else None
            ),
        )
        task = self._store.create_task(task)
        self._register_scheduled_jobs(task)
        return task

    def create_after_task(
        self,
        *,
        instruction: str,
        after_seconds: int,
        source_session_key: str,
        channel: str,
        chat_id: str,
    ) -> Task:
        """创建一次性延时任务。"""
        return self.create_task(
            instruction=instruction,
            schedule=self.build_schedule(after_seconds=after_seconds),
            turn=1,
            mode="scheduled",
            source_session_key=source_session_key,
            channel=channel,
            chat_id=chat_id,
        )

    def create_at_task(
        self,
        *,
        instruction: str,
        at: str,
        source_session_key: str,
        channel: str,
        chat_id: str,
    ) -> Task:
        """创建一次性定点任务。"""
        return self.create_task(
            instruction=instruction,
            schedule=self.build_schedule(at=at),
            turn=1,
            mode="scheduled",
            source_session_key=source_session_key,
            channel=channel,
            chat_id=chat_id,
        )

    def create_daily_task(
        self,
        *,
        instruction: str,
        daily_time: str,
        source_session_key: str,
        channel: str,
        chat_id: str,
    ) -> Task:
        """创建每天固定时间重复任务。"""
        return self.create_task(
            instruction=instruction,
            schedule=self.build_schedule(daily_time=daily_time),
            turn=None,
            mode="scheduled",
            source_session_key=source_session_key,
            channel=channel,
            chat_id=chat_id,
        )

    def create_every_task(
        self,
        *,
        instruction: str,
        every_seconds: int,
        source_session_key: str,
        channel: str,
        chat_id: str,
    ) -> Task:
        """创建固定间隔重复任务。"""
        return self.create_task(
            instruction=instruction,
            schedule=self.build_schedule(every_seconds=every_seconds),
            turn=None,
            mode="scheduled",
            source_session_key=source_session_key,
            channel=channel,
            chat_id=chat_id,
        )

    def update_task(
        self,
        task_id: str,
        *,
        instruction: str | None = None,
        schedule: CronSchedule | None = None,
        turn: int | None = None,
        update_turn: bool = False,
        mode: Literal["scheduled", "prepared_delivery"] | None = None,
    ) -> Task | None:
        """更新一条任务。"""
        task = self._store.get_task(task_id)
        if task is None:
            return None
        if instruction is not None:
            normalized = instruction.strip()
            if not normalized:
                raise ValueError("instruction must not be empty")
            task.payload.instruction = normalized
            task.title = self._build_title(normalized)
        if schedule is not None:
            task.schedule = schedule
        if update_turn:
            task.turn = turn
        if mode is not None:
            task.execution_type = mode
        if task.execution_type == "prepared_delivery":
            task.deliver_at_ms = task.schedule.at_ms
            task.prepare_before_ms = task.prepare_before_ms or self.DEFAULT_PREPARE_BEFORE_MS
        else:
            task.deliver_at_ms = None
            task.prepare_before_ms = None
        self._validate_turn(task.schedule, task.turn)
        task.enabled = True
        self._store.update_task(task)
        self._register_scheduled_jobs(task)
        return task

    def delete_task(self, task_id: str) -> bool:
        """删除一条任务及其触发器。"""
        self._cron.remove_jobs_for_target("task", task_id)
        return self._store.remove_task(task_id)

    def enable_task(self, task_id: str) -> Task | None:
        """启用一条任务并重新注册触发器。"""
        task = self._store.get_task(task_id)
        if task is None:
            return None
        task.enabled = True
        self._store.update_task(task)
        self._register_scheduled_jobs(task)
        return task

    def disable_task(self, task_id: str) -> Task | None:
        """停用一条任务并撤销触发器。"""
        task = self._store.get_task(task_id)
        if task is None:
            return None
        task.enabled = False
        self._store.update_task(task)
        self._cron.remove_jobs_for_target("task", task_id)
        return task

    def update_instruction(self, task_id: str, instruction: str) -> Task | None:
        """只更新任务内容。"""
        return self.update_task(task_id, instruction=instruction)

    def reschedule_after(self, task_id: str, *, after_seconds: int) -> Task | None:
        """把任务改成一次性延时执行。"""
        return self.update_task(
            task_id,
            schedule=self.build_schedule(after_seconds=after_seconds),
            turn=1,
            update_turn=True,
        )

    def reschedule_at(self, task_id: str, *, at: str) -> Task | None:
        """把任务改成一次性定点执行。"""
        return self.update_task(
            task_id,
            schedule=self.build_schedule(at=at),
            turn=1,
            update_turn=True,
        )

    def reschedule_daily(self, task_id: str, *, daily_time: str) -> Task | None:
        """把任务改成每天固定时间执行。"""
        return self.update_task(
            task_id,
            schedule=self.build_schedule(daily_time=daily_time),
            turn=None,
            update_turn=True,
        )

    def reschedule_every(self, task_id: str, *, every_seconds: int) -> Task | None:
        """把任务改成固定间隔执行。"""
        return self.update_task(
            task_id,
            schedule=self.build_schedule(every_seconds=every_seconds),
            turn=None,
            update_turn=True,
        )

    def next_run_for_task(self, task_id: str) -> int | None:
        """返回任务下一次可见执行时间。"""
        jobs = [
            job for job in self._cron.list_jobs(include_disabled=True)
            if job.payload.target_kind == "task"
            and job.payload.target_id == task_id
            and job.enabled
            and job.state.next_run_at_ms is not None
            and job.payload.phase in {"run", "deliver"}
        ]
        if not jobs:
            return None
        return min(job.state.next_run_at_ms for job in jobs if job.state.next_run_at_ms is not None)

    @staticmethod
    def build_task_trigger_message(
        task: Task,
        *,
        stage: TaskPhase,
        extra_note: str | None = None,
    ) -> str:
        """构造写回主会话的结构化任务触发消息。"""
        lines = [
            "[Auto Task]",
            f"task_id: {task.id}",
            f"stage: {stage}",
            f"execution_type: {task.execution_type}",
            f"title: {task.title}",
            f"instruction: {task.payload.instruction}",
        ]
        if extra_note:
            lines.append(f"note: {extra_note}")
        return "\n".join(lines)

    async def _run_agent_task(
        self,
        task: Task,
        *,
        stage: TaskPhase,
        extra_note: str | None = None,
        write_to_main_session: bool,
    ) -> str:
        """通过 agent 主链路执行一次任务。"""
        prompt = self.build_task_trigger_message(
            task,
            stage=stage,
            extra_note=extra_note,
        )

        async def _noop_progress(_content: str, *, tool_hint: bool = False) -> None:
            del tool_hint

        task_tool = self._loop.tools.get("task_create_after")
        token = None
        setter = getattr(task_tool, "set_task_context", None)
        if callable(setter):
            token = setter(True)
        try:
            result = await self._loop.process_direct_result(
                prompt,
                session_key=(
                    task.source_session_key
                    if write_to_main_session
                    else f"task:{task.id}"
                ),
                channel=task.target_channel,
                chat_id=task.target_chat_id,
                on_progress=_noop_progress,
                persist_session=write_to_main_session,
            )
        finally:
            resetter = getattr(task_tool, "reset_task_context", None)
            if callable(resetter) and token is not None:
                resetter(token)

        return str(result.final_content or "").strip()

    def _disable_task_if_exhausted(self, task: Task) -> None:
        """根据 turn 自动停用已完成任务。"""
        if task.turn is None:
            self._store.update_task(task)
            return
        if task.run.run_count < task.turn:
            self._store.update_task(task)
            return
        task.enabled = False
        self._store.update_task(task)
        self._cron.remove_jobs_for_target("task", task.id)

    async def _run_scheduled(self, task: Task) -> None:
        """执行一条普通定时任务。"""
        task.run.status = "running"
        task.run.error = None
        self._store.update_task(task)
        try:
            final_text = await self._run_agent_task(
                task,
                stage="run",
                write_to_main_session=True,
            )
            if not final_text:
                raise ValueError("empty task response")
            await self._delivery.deliver(
                task_id=task.id,
                channel=task.target_channel,
                chat_id=task.target_chat_id,
                content=final_text,
            )
            task.run.status = "delivered"
            task.run.error = None
        except Exception as exc:
            logger.exception("Task {} failed during scheduled execution", task.id)
            task.run.status = "failed"
            task.run.error = str(exc)
            await self._delivery.deliver(
                task_id=task.id,
                channel=task.target_channel,
                chat_id=task.target_chat_id,
                content=f"自动任务执行失败：{exc}",
            )
        task.run.last_run_at_ms = _now_ms()
        task.run.run_count += 1
        self._disable_task_if_exhausted(task)

    async def _prepare_delivery(self, task: Task) -> None:
        """执行 prepared_delivery 的准备阶段。"""
        task.run.status = "preparing"
        task.run.error = None
        self._store.update_task(task)
        try:
            prepared = await self._run_agent_task(
                task,
                stage="prepare",
                extra_note="现在先准备最终要发送的内容，稍后到点时会直接投递这份结果。",
                write_to_main_session=False,
            )
            if not prepared:
                raise ValueError("empty prepared result")
            task.run.prepared_result = prepared
            task.run.prepared_at_ms = _now_ms()
            task.run.status = "prepared"
            task.run.error = None
        except Exception as exc:
            logger.exception("Task {} failed during preparation", task.id)
            task.run.prepared_result = None
            task.run.prepared_at_ms = None
            task.run.status = "failed"
            task.run.error = str(exc)
        self._store.update_task(task)

    async def _deliver_prepared(self, task: Task) -> None:
        """执行 prepared_delivery 的最终投递阶段。"""
        task.run.status = "running"
        self._store.update_task(task)
        content = str(task.run.prepared_result or "").strip()
        if not content:
            content = await self._run_agent_task(
                task,
                stage="deliver",
                extra_note=(
                    "预先准备结果缺失或失败，请现在直接生成一条最终发给用户的任务结果，"
                    "并在内容里自然说明这是补救发送。"
                ),
                write_to_main_session=True,
            )
            if not content:
                content = "自动任务准备失败，这次没能生成可发送的内容。"
        await self._delivery.deliver(
            task_id=task.id,
            channel=task.target_channel,
            chat_id=task.target_chat_id,
            content=content,
        )
        task.run.status = "delivered"
        task.run.last_run_at_ms = _now_ms()
        task.run.run_count += 1
        task.run.prepared_result = None
        task.run.prepared_at_ms = None
        task.run.error = None
        self._disable_task_if_exhausted(task)

    async def run_trigger(self, job: CronJob) -> None:
        """处理一条到点触发记录。"""
        payload = job.payload
        if payload.target_kind != "task":
            return
        task = self._store.get_task(payload.target_id)
        if task is None:
            logger.warning("Skip missing task {}", payload.target_id)
            self._cron.remove_job(job.id)
            return
        if not task.enabled:
            self._cron.remove_jobs_for_target("task", task.id)
            return
        if payload.phase == "prepare":
            await self._prepare_delivery(task)
            return
        if payload.phase == "deliver":
            await self._deliver_prepared(task)
            return
        await self._run_scheduled(task)
