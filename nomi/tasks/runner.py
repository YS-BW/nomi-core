"""自动任务 orchestrator。"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import fcntl

from loguru import logger

from nomi.cron import CronJob, CronSchedule, CronService
from nomi.cron.types import CronJobState, CronPayload
from nomi.config.paths import get_logs_dir, get_reminder_store_path
from nomi.tasks.models import Task, TaskPayload
from nomi.tasks.reminder_store import ReminderStore
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
    DEFAULT_EXECUTION_TIMEOUT_SECONDS = 180
    SCHEDULER_LOCK_FILE = "task_scheduler.lock"

    def __init__(self, loop: "AgentLoop", store: TaskStore, cron_service: CronService) -> None:
        """初始化任务 orchestrator。"""
        self._loop = loop
        self._store = store
        self._cron = cron_service
        self._reminders = ReminderStore(get_reminder_store_path())
        self._scheduler_lock_handle = None
        self._scheduler_owner = False
        self._last_reconciled_store_mtime_ns: int | None = None
        self._scheduler_owner_name = (
            str(getattr(loop, "reminder_consumer", None) or "").strip() or "cli"
        )
        loaded_config = getattr(loop, "config", None)
        if loaded_config is not None:
            self._task_execution_timeout_seconds = int(
                loaded_config.agents.defaults.task_execution_timeout_seconds
            )
        else:
            self._task_execution_timeout_seconds = self.DEFAULT_EXECUTION_TIMEOUT_SECONDS

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
        if not task.enabled:
            return
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

    def _build_task_jobs(self, task: Task) -> list[CronJob]:
        """根据任务定义构造一组派生 cron job。"""
        if not task.enabled:
            return []
        now_ms = _now_ms()
        jobs: list[CronJob] = []
        if task.execution_type == "scheduled":
            next_run_at_ms = self._cron._compute_next_run(task.schedule, now_ms)  # noqa: SLF001
            if next_run_at_ms is None:
                return []
            jobs.append(
                CronJob(
                    id=f"cron_task_{task.id}_run",
                    name=task.title,
                    enabled=True,
                    schedule=task.schedule,
                    payload=CronPayload(target_kind="task", target_id=task.id, phase="run"),
                    state=CronJobState(next_run_at_ms=next_run_at_ms),
                    created_at_ms=task.created_at_ms or now_ms,
                    updated_at_ms=task.updated_at_ms or now_ms,
                    delete_after_run=task.schedule.kind == "at",
                )
            )
            return jobs
        if task.schedule.kind != "at" or task.deliver_at_ms is None:
            raise ValueError("prepared_delivery currently requires a one-shot deliver time")
        prepare_before_ms = task.prepare_before_ms or self.DEFAULT_PREPARE_BEFORE_MS
        prepare_at_ms = task.deliver_at_ms - prepare_before_ms
        if prepare_at_ms > now_ms:
            jobs.append(
                CronJob(
                    id=f"cron_task_{task.id}_prepare",
                    name=f"{task.title}:prepare",
                    enabled=True,
                    schedule=CronSchedule(kind="at", at_ms=prepare_at_ms),
                    payload=CronPayload(target_kind="task", target_id=task.id, phase="prepare"),
                    state=CronJobState(next_run_at_ms=prepare_at_ms),
                    created_at_ms=task.created_at_ms or now_ms,
                    updated_at_ms=task.updated_at_ms or now_ms,
                    delete_after_run=True,
                )
            )
        if task.deliver_at_ms > now_ms:
            jobs.append(
                CronJob(
                    id=f"cron_task_{task.id}_deliver",
                    name=f"{task.title}:deliver",
                    enabled=True,
                    schedule=CronSchedule(kind="at", at_ms=task.deliver_at_ms),
                    payload=CronPayload(target_kind="task", target_id=task.id, phase="deliver"),
                    state=CronJobState(next_run_at_ms=task.deliver_at_ms),
                    created_at_ms=task.created_at_ms or now_ms,
                    updated_at_ms=task.updated_at_ms or now_ms,
                    delete_after_run=True,
                )
            )
        return jobs

    def _has_live_task_job(self, task_id: str) -> bool:
        """判断任务当前是否仍有派生 task cron。"""
        return any(
            job.payload.target_kind == "task" and job.payload.target_id == task_id
            for job in self._cron.list_jobs(include_disabled=True)
        )

    def _recover_stale_running_tasks(self) -> int:
        """恢复没有对应 cron 的陈旧 running task。"""
        recovered = 0
        self._store.reload_tasks()
        for task in self._store.list_tasks(include_disabled=True):
            if task.run.status != "running":
                continue
            if self._has_live_task_job(task.id):
                continue
            task.run.status = "failed"
            task.run.error = "task execution timeout recovery: stale running task without live cron job"
            task.run.last_run_at_ms = _now_ms()
            task.run.run_count = max(1, task.run.run_count)
            logger.warning(
                "Recovered stale running task: task_id={} session_id={} target_channel={} owner={}",
                task.id,
                task.source_session_key,
                task.target_channel,
                self._scheduler_owner_name,
            )
            self._store.update_task(task)
            recovered += 1
        return recovered

    def get_scheduler_snapshot(self) -> dict[str, str | bool]:
        """返回 task scheduler owner 快照。"""
        return {
            "owner": self._scheduler_owner_name,
            "active": self._scheduler_owner,
            "lock_path": str(self._scheduler_lock_path()),
        }

    def set_scheduler_owner_name(self, owner: str) -> None:
        """更新当前 runtime 的 scheduler owner 展示名。"""
        normalized = str(owner or "").strip()
        self._scheduler_owner_name = normalized or "cli"

    def read_scheduler_owner_info(self) -> dict[str, str]:
        """从锁文件读取 scheduler owner 元信息。"""
        lock_path = self._scheduler_lock_path()
        if not lock_path.exists():
            return {}
        try:
            payload = json.loads(lock_path.read_text(encoding="utf-8").strip() or "{}")
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): str(value) for key, value in payload.items()}

    def reconcile_scheduled_jobs(self) -> int:
        """按当前任务定义重建全部 task 类 cron 触发器。"""
        jobs: list[CronJob] = []
        recovered = self._recover_stale_running_tasks()
        self._store.reload_tasks()
        for task in self._store.list_tasks(include_disabled=True):
            jobs.extend(self._build_task_jobs(task))
        self._cron.replace_jobs_for_target_kind("task", jobs)
        try:
            self._last_reconciled_store_mtime_ns = self._store.store_path.stat().st_mtime_ns
        except FileNotFoundError:
            self._last_reconciled_store_mtime_ns = None
        if recovered:
            logger.info(
                "Task reconcile recovered {} stale running task(s) before rebuilding cron jobs",
                recovered,
            )
        return len(jobs)

    def poll_scheduler(self) -> bool:
        """在 owner runtime 中按需重建 task cron。"""
        if not self._scheduler_owner:
            return False
        try:
            current_mtime_ns = self._store.store_path.stat().st_mtime_ns
        except FileNotFoundError:
            current_mtime_ns = None
        if current_mtime_ns == self._last_reconciled_store_mtime_ns:
            return False
        self.reconcile_scheduled_jobs()
        return True

    def _scheduler_lock_path(self) -> Path:
        """返回实例级 scheduler owner 锁文件路径。"""
        return get_logs_dir() / self.SCHEDULER_LOCK_FILE

    def _resolve_global_reminder_targets(self, source_session_key: str) -> list[str]:
        """根据当前实例运行态解析全局提醒 fanout 目标。"""
        targets: list[str] = []
        source_channel = source_session_key.split(":", 1)[0] if ":" in source_session_key else source_session_key

        if source_channel == "cli":
            targets.append("cli")

        try:
            runtime_state_path = get_logs_dir() / "runtime-service.json"
            if runtime_state_path.exists():
                import json

                payload = json.loads(runtime_state_path.read_text(encoding="utf-8"))
                remote = payload.get("remote") if isinstance(payload.get("remote"), dict) else {}
                channel = payload.get("channel") if isinstance(payload.get("channel"), dict) else {}
                if remote.get("running"):
                    targets.append("remote")
                owner = str(channel.get("kind") or "").strip()
                if channel.get("running") and owner:
                    targets.append(owner)
        except Exception:
            pass

        return sorted(set(targets))

    def enqueue_global_reminder(self, *, task_id: str, session_id: str, content: str) -> bool:
        """把任务结果写入实例级全局提醒队列。"""
        targets = self._resolve_global_reminder_targets(session_id)
        delivery = self._reminders.enqueue(
            task_id=task_id,
            session_id=session_id,
            content=content,
            targets=targets,
        )
        if delivery is None:
            logger.warning(
                "Global reminder skipped: task_id={} session_id={} owner={} reason=no_targets",
                task_id,
                session_id,
                self._scheduler_owner_name,
            )
            return False
        logger.info(
            "Global reminder enqueued: task_id={} session_id={} owner={} targets={}",
            task_id,
            session_id,
            self._scheduler_owner_name,
            ",".join(targets),
        )
        return delivery is not None

    def list_pending_reminders(self, consumer: str):
        """列出当前 consumer 尚未发送的提醒。"""
        return self._reminders.list_pending(consumer)

    def mark_reminder_delivered(self, delivery_id: str, consumer: str) -> bool:
        """标记当前 consumer 已完成提醒投递。"""
        return self._reminders.mark_delivered(delivery_id, consumer)

    def start_scheduler(self) -> bool:
        """尝试成为当前实例的 scheduler owner。"""
        lock_path = self._scheduler_lock_path()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            self._scheduler_owner = False
            logger.warning(
                "Task scheduler owner already exists for instance; current runtime stays in follower mode"
            )
            return False
        handle.seek(0)
        handle.truncate()
        handle.write(
            json.dumps(
                {
                    "owner": self._scheduler_owner_name,
                    "acquired_at_ms": _now_ms(),
                    "bus": self._loop.bus.__class__.__name__,
                },
                ensure_ascii=False,
            )
        )
        handle.write("\n")
        handle.flush()
        self._scheduler_lock_handle = handle
        self._scheduler_owner = True
        self.reconcile_scheduled_jobs()
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.info("Task scheduler owner acquired without active event loop; defer cron start")
            return True
        self._cron.start()
        logger.info("Task scheduler owner acquired for current instance")
        return True

    async def stop_scheduler(self) -> None:
        """停止当前 runtime 的 scheduler owner 状态。"""
        if self._scheduler_owner:
            await self._cron.stop()
        handle = self._scheduler_lock_handle
        self._scheduler_lock_handle = None
        self._scheduler_owner = False
        if handle is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    @property
    def scheduler_owner(self) -> bool:
        """返回当前 runtime 是否持有 scheduler owner。"""
        return self._scheduler_owner

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
        target_channel: str | None = None,
        target_chat_id: str | None = None,
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
            target_channel=target_channel or channel,
            target_chat_id=target_chat_id or chat_id,
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
        target_channel: str | None = None,
        target_chat_id: str | None = None,
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
            target_channel=target_channel,
            target_chat_id=target_chat_id,
        )

    def create_at_task(
        self,
        *,
        instruction: str,
        at: str,
        source_session_key: str,
        channel: str,
        chat_id: str,
        target_channel: str | None = None,
        target_chat_id: str | None = None,
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
            target_channel=target_channel,
            target_chat_id=target_chat_id,
        )

    def create_daily_task(
        self,
        *,
        instruction: str,
        daily_time: str,
        source_session_key: str,
        channel: str,
        chat_id: str,
        target_channel: str | None = None,
        target_chat_id: str | None = None,
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
            target_channel=target_channel,
            target_chat_id=target_chat_id,
        )

    def create_every_task(
        self,
        *,
        instruction: str,
        every_seconds: int,
        source_session_key: str,
        channel: str,
        chat_id: str,
        target_channel: str | None = None,
        target_chat_id: str | None = None,
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
            target_channel=target_channel,
            target_chat_id=target_chat_id,
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
        use_source_session_history: bool,
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
            task_session_key = f"task:{task.id}:{stage}"
            result = await asyncio.wait_for(
                self._loop.process_direct_result(
                    prompt,
                    session_key=task_session_key,
                    channel=task.target_channel,
                    chat_id=task.target_chat_id,
                    history_session_key=(
                        task.source_session_key if use_source_session_history else None
                    ),
                    on_progress=_noop_progress,
                    persist_session=False,
                ),
                timeout=self._task_execution_timeout_seconds,
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
        logger.info(
            "Task execution started: task_id={} session_id={} target_channel={} owner={} phase=run",
            task.id,
            task.source_session_key,
            task.target_channel,
            self._scheduler_owner_name,
        )
        try:
            final_text = await self._run_agent_task(
                task,
                stage="run",
                use_source_session_history=True,
            )
            if not final_text:
                raise ValueError("empty task response")
            enqueued = self.enqueue_global_reminder(
                task_id=task.id,
                session_id=task.source_session_key,
                content=final_text,
            )
            task.run.status = "delivered"
            task.run.error = None
            logger.info(
                "Task execution finished: task_id={} session_id={} target_channel={} owner={} phase=run reminder_enqueued={}",
                task.id,
                task.source_session_key,
                task.target_channel,
                self._scheduler_owner_name,
                enqueued,
            )
        except asyncio.CancelledError:
            task.run.status = "failed"
            task.run.error = "task execution cancelled by scheduler owner interruption"
            task.run.last_run_at_ms = _now_ms()
            task.run.run_count += 1
            self._store.update_task(task)
            logger.warning(
                "Task execution cancelled: task_id={} session_id={} target_channel={} owner={} phase=run",
                task.id,
                task.source_session_key,
                task.target_channel,
                self._scheduler_owner_name,
            )
            raise
        except asyncio.TimeoutError:
            task.run.status = "failed"
            task.run.error = (
                f"task execution timed out after {self._task_execution_timeout_seconds}s"
            )
            self.enqueue_global_reminder(
                task_id=task.id,
                session_id=task.source_session_key,
                content=f"自动任务执行失败：{task.run.error}",
            )
            logger.warning(
                "Task execution timed out: task_id={} session_id={} target_channel={} owner={} phase=run timeout_seconds={}",
                task.id,
                task.source_session_key,
                task.target_channel,
                self._scheduler_owner_name,
                self._task_execution_timeout_seconds,
            )
        except Exception as exc:
            logger.exception("Task {} failed during scheduled execution", task.id)
            task.run.status = "failed"
            task.run.error = str(exc)
            self.enqueue_global_reminder(
                task_id=task.id,
                session_id=task.source_session_key,
                content=f"自动任务执行失败：{exc}",
            )
            logger.warning(
                "Task execution failed: task_id={} session_id={} target_channel={} owner={} phase=run error={}",
                task.id,
                task.source_session_key,
                task.target_channel,
                self._scheduler_owner_name,
                exc,
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
                use_source_session_history=True,
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
        logger.info(
            "Task execution started: task_id={} session_id={} target_channel={} owner={} phase=deliver",
            task.id,
            task.source_session_key,
            task.target_channel,
            self._scheduler_owner_name,
        )
        content = str(task.run.prepared_result or "").strip()
        try:
            if not content:
                content = await self._run_agent_task(
                    task,
                    stage="deliver",
                    extra_note=(
                        "预先准备结果缺失或失败，请现在直接生成一条最终发给用户的任务结果，"
                        "并在内容里自然说明这是补救发送。"
                    ),
                    use_source_session_history=True,
                )
                if not content:
                    content = "自动任务准备失败，这次没能生成可发送的内容。"
            enqueued = self.enqueue_global_reminder(
                task_id=task.id,
                session_id=task.source_session_key,
                content=content,
            )
            task.run.status = "delivered"
            task.run.error = None
            logger.info(
                "Task execution finished: task_id={} session_id={} target_channel={} owner={} phase=deliver reminder_enqueued={}",
                task.id,
                task.source_session_key,
                task.target_channel,
                self._scheduler_owner_name,
                enqueued,
            )
        except asyncio.CancelledError:
            task.run.status = "failed"
            task.run.error = "task execution cancelled by scheduler owner interruption"
            task.run.last_run_at_ms = _now_ms()
            task.run.run_count += 1
            task.run.prepared_result = None
            task.run.prepared_at_ms = None
            self._store.update_task(task)
            logger.warning(
                "Task execution cancelled: task_id={} session_id={} target_channel={} owner={} phase=deliver",
                task.id,
                task.source_session_key,
                task.target_channel,
                self._scheduler_owner_name,
            )
            raise
        except asyncio.TimeoutError:
            task.run.status = "failed"
            task.run.error = (
                f"task execution timed out after {self._task_execution_timeout_seconds}s"
            )
            self.enqueue_global_reminder(
                task_id=task.id,
                session_id=task.source_session_key,
                content=f"自动任务执行失败：{task.run.error}",
            )
            logger.warning(
                "Task execution timed out: task_id={} session_id={} target_channel={} owner={} phase=deliver timeout_seconds={}",
                task.id,
                task.source_session_key,
                task.target_channel,
                self._scheduler_owner_name,
                self._task_execution_timeout_seconds,
            )
        except Exception as exc:
            task.run.status = "failed"
            task.run.error = str(exc)
            self.enqueue_global_reminder(
                task_id=task.id,
                session_id=task.source_session_key,
                content=f"自动任务执行失败：{exc}",
            )
            logger.warning(
                "Task execution failed: task_id={} session_id={} target_channel={} owner={} phase=deliver error={}",
                task.id,
                task.source_session_key,
                task.target_channel,
                self._scheduler_owner_name,
                exc,
            )
        task.run.last_run_at_ms = _now_ms()
        task.run.run_count += 1
        task.run.prepared_result = None
        task.run.prepared_at_ms = None
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
