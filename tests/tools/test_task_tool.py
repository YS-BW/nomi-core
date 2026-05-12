from __future__ import annotations

from types import SimpleNamespace

import pytest

from nomi.bus.events import OutboundMessage
from nomi.config.schema import Config
from nomi.agent.tools.tasks import (
    TaskCreateAfterTool,
    TaskCreateAtTool,
    TaskCreateDailyTool,
    TaskCreateEveryTool,
    TaskDeleteTool,
    TaskDisableTool,
    TaskEnableTool,
    TaskGetTool,
    TaskListTool,
    TaskRescheduleAfterTool,
    TaskRescheduleAtTool,
    TaskRescheduleDailyTool,
    TaskRescheduleEveryTool,
    TaskUpdateInstructionTool,
)
from nomi.bus.queue import MessageBus
from nomi.cron import CronService
from nomi.session.manager import SessionManager
from nomi.tasks import TaskRunner, TaskStore
from nomi.agent.execution.processor import TurnProcessor
from nomi.agent.execution.turn_journal import TurnJournalRecord
from nomi.bus.events import InboundMessage


def _make_tools(tmp_path):
    config = Config()
    loop_stub = type(
        "LoopStub",
        (),
        {
            "context": type("Ctx", (), {"timezone": "Asia/Shanghai"})(),
            "bus": None,
            "tools": type("Tools", (), {"get": lambda *_args, **_kwargs: None})(),
            "process_direct_result": None,
            "config": config,
            "reminder_consumer": "cli",
        },
    )()
    cron_service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")
    runner = TaskRunner(
        loop=loop_stub,  # type: ignore[arg-type]
        store=TaskStore(tmp_path / "tasks" / "tasks.json"),
        cron_service=cron_service,
    )
    runner._reminders = runner._reminders.__class__(tmp_path / "tasks-runtime" / "reminders.json")
    create_after = TaskCreateAfterTool(runner, default_timezone="Asia/Shanghai")
    create_after.set_context("cli", "direct")
    create_at = TaskCreateAtTool(runner, default_timezone="Asia/Shanghai")
    create_at.set_context("cli", "direct")
    create_daily = TaskCreateDailyTool(runner, default_timezone="Asia/Shanghai")
    create_daily.set_context("cli", "direct")
    create_every = TaskCreateEveryTool(runner, default_timezone="Asia/Shanghai")
    create_every.set_context("cli", "direct")
    return {
        "runner": runner,
        "cron_service": cron_service,
        "task_create_after": create_after,
        "task_create_at": create_at,
        "task_create_daily": create_daily,
        "task_create_every": create_every,
        "task_list": TaskListTool(runner, default_timezone="Asia/Shanghai"),
        "task_get": TaskGetTool(runner, default_timezone="Asia/Shanghai"),
        "task_delete": TaskDeleteTool(runner, default_timezone="Asia/Shanghai"),
        "task_enable": TaskEnableTool(runner, default_timezone="Asia/Shanghai"),
        "task_disable": TaskDisableTool(runner, default_timezone="Asia/Shanghai"),
        "task_update_instruction": TaskUpdateInstructionTool(runner, default_timezone="Asia/Shanghai"),
        "task_reschedule_after": TaskRescheduleAfterTool(runner, default_timezone="Asia/Shanghai"),
        "task_reschedule_at": TaskRescheduleAtTool(runner, default_timezone="Asia/Shanghai"),
        "task_reschedule_daily": TaskRescheduleDailyTool(runner, default_timezone="Asia/Shanghai"),
        "task_reschedule_every": TaskRescheduleEveryTool(runner, default_timezone="Asia/Shanghai"),
    }


async def test_task_create_after_list_get_delete(tmp_path) -> None:
    tools = _make_tools(tmp_path)

    created = await tools["task_create_after"].execute(
        instruction="提醒我吃药",
        after_seconds=120,
    )

    assert "已创建自动任务" in created
    listed = await tools["task_list"].execute()
    assert "当前有 1 个自动任务" in listed
    assert "instruction: 提醒我吃药" in listed
    task = tools["runner"].list_tasks(include_disabled=True)[0]
    got = await tools["task_get"].execute(task_id=task.id)
    assert f"task_id: {task.id}" in got
    assert "schedule kind: after" in got
    removed = await tools["task_delete"].execute(task_id=task.id)
    assert removed == f"已删除自动任务：`{task.id}`"
    assert tools["cron_service"].list_jobs(include_disabled=True) == []


async def test_task_create_at_uses_default_timezone_in_output(tmp_path) -> None:
    tools = _make_tools(tmp_path)
    result = await tools["task_create_at"].execute(
        instruction="明天早上提醒我",
        at="2099-04-29T09:30:00",
    )
    assert "已创建自动任务" in result
    listed = await tools["task_list"].execute()
    assert "(Asia/Shanghai)" in listed


async def test_task_create_daily_and_every_map_to_repeating_tasks(tmp_path) -> None:
    tools = _make_tools(tmp_path)
    await tools["task_create_daily"].execute(
        instruction="提醒我睡觉",
        daily_time="23:00",
    )
    await tools["task_create_every"].execute(
        instruction="提醒我喝水",
        every_seconds=7200,
    )
    tasks = tools["runner"].list_tasks(include_disabled=True)
    assert len(tasks) == 2
    daily_task = next(task for task in tasks if task.payload.instruction == "提醒我睡觉")
    every_task = next(task for task in tasks if task.payload.instruction == "提醒我喝水")
    assert daily_task.turn is None
    assert daily_task.schedule.kind == "cron"
    assert every_task.turn is None
    assert every_task.schedule.kind == "every"


async def test_task_get_delete_enable_disable_require_task_id(tmp_path) -> None:
    tools = _make_tools(tmp_path)
    assert await tools["task_get"].execute() == "Error: task_id is required"
    assert await tools["task_delete"].execute() == "Error: task_id is required"
    assert await tools["task_enable"].execute() == "Error: task_id is required"
    assert await tools["task_disable"].execute() == "Error: task_id is required"


async def test_task_disable_and_enable_affect_enabled_flag_and_jobs(tmp_path) -> None:
    tools = _make_tools(tmp_path)
    await tools["task_create_daily"].execute(
        instruction="提醒我睡觉",
        daily_time="23:00",
    )
    task = tools["runner"].list_tasks(include_disabled=True)[0]

    disabled = await tools["task_disable"].execute(task_id=task.id)
    assert disabled == f"已停用自动任务：`{task.id}`（提醒我睡觉）"
    assert tools["runner"].get_task(task.id).enabled is False
    assert tools["cron_service"].list_jobs(include_disabled=True) == []

    enabled = await tools["task_enable"].execute(task_id=task.id)
    assert enabled == f"已启用自动任务：`{task.id}`（提醒我睡觉）"
    assert tools["runner"].get_task(task.id).enabled is True
    jobs = [job for job in tools["cron_service"].list_jobs(include_disabled=True) if job.payload.target_id == task.id]
    assert len(jobs) == 1


async def test_task_update_instruction_rewrites_only_content(tmp_path) -> None:
    tools = _make_tools(tmp_path)
    await tools["task_create_every"].execute(
        instruction="打开微信",
        every_seconds=60,
    )
    task_id = tools["runner"].list_tasks(include_disabled=True)[0].id
    result = await tools["task_update_instruction"].execute(
        task_id=task_id,
        instruction="打开浏览器",
    )
    assert result == f"已更新自动任务：`{task_id}`（打开浏览器）"
    listed = await tools["task_list"].execute()
    assert "instruction: 打开浏览器" in listed
    assert "instruction: 打开微信" not in listed


async def test_task_reschedule_tools_switch_schedule_kind_and_turn(tmp_path) -> None:
    tools = _make_tools(tmp_path)
    await tools["task_create_every"].execute(
        instruction="提醒我看书",
        every_seconds=60,
    )
    task_id = tools["runner"].list_tasks(include_disabled=True)[0].id

    result = await tools["task_reschedule_after"].execute(
        task_id=task_id,
        after_seconds=120,
    )
    assert result == f"已更新自动任务：`{task_id}`（提醒我看书）"
    task = tools["runner"].get_task(task_id)
    assert task is not None
    assert task.schedule.kind == "at"
    assert task.turn == 1

    result = await tools["task_reschedule_at"].execute(
        task_id=task_id,
        at="2099-04-29T09:30:00",
    )
    assert result == f"已更新自动任务：`{task_id}`（提醒我看书）"
    task = tools["runner"].get_task(task_id)
    assert task is not None
    assert task.schedule.kind == "at"
    assert task.turn == 1

    result = await tools["task_reschedule_daily"].execute(
        task_id=task_id,
        daily_time="08:00",
    )
    assert result == f"已更新自动任务：`{task_id}`（提醒我看书）"
    task = tools["runner"].get_task(task_id)
    assert task is not None
    assert task.schedule.kind == "cron"
    assert task.turn is None

    result = await tools["task_reschedule_every"].execute(
        task_id=task_id,
        every_seconds=1800,
    )
    assert result == f"已更新自动任务：`{task_id}`（提醒我看书）"
    task = tools["runner"].get_task(task_id)
    assert task is not None
    assert task.schedule.kind == "every"
    assert task.turn is None


async def test_task_reschedule_tools_require_target_fields(tmp_path) -> None:
    tools = _make_tools(tmp_path)
    assert await tools["task_update_instruction"].execute(task_id="task_1") == "Error: instruction is required"
    assert await tools["task_reschedule_after"].execute(task_id="task_1") == "Error: after_seconds is required"
    assert await tools["task_reschedule_at"].execute(task_id="task_1") == "Error: at is required"
    assert await tools["task_reschedule_daily"].execute(task_id="task_1") == "Error: daily_time is required"
    assert await tools["task_reschedule_every"].execute(task_id="task_1") == "Error: every_seconds is required"


def test_build_task_trigger_message_uses_structured_block(tmp_path) -> None:
    tools = _make_tools(tmp_path)
    runner = tools["runner"]
    task = runner.create_after_task(
        instruction="提醒用户吃饭",
        after_seconds=60,
        source_session_key="weixin:wx-user",
        channel="weixin",
        chat_id="wx-user",
    )

    message = runner.build_task_trigger_message(task, stage="run")

    assert "[Auto Task]" in message
    assert f"task_id: {task.id}" in message
    assert "stage: run" in message
    assert "execution_type: scheduled" in message
    assert "title: 提醒用户吃饭" in message
    assert "instruction: 提醒用户吃饭" in message


async def test_run_agent_task_uses_main_session_for_run_stage(tmp_path) -> None:
    tools = _make_tools(tmp_path)
    runner = tools["runner"]
    task = runner.create_after_task(
        instruction="提醒用户吃饭",
        after_seconds=60,
        source_session_key="weixin:wx-user",
        channel="weixin",
        chat_id="wx-user",
    )

    calls: list[dict[str, str]] = []

    async def _fake_process_direct_result(
        content,
        session_key,
        channel,
        chat_id,
        history_session_key=None,
        on_progress=None,
        persist_session=True,
    ):
        del on_progress
        calls.append({
            "content": content,
            "session_key": session_key,
            "channel": channel,
            "chat_id": chat_id,
            "history_session_key": str(history_session_key),
            "persist_session": str(persist_session),
        })
        return SimpleNamespace(final_content="该吃饭啦")

    runner._loop.process_direct_result = _fake_process_direct_result
    await runner._run_agent_task(task, stage="run", use_source_session_history=True)

    assert calls[0]["session_key"] == f"task:{task.id}:run"
    assert calls[0]["history_session_key"] == "weixin:wx-user"
    assert calls[0]["persist_session"] == "False"
    assert "[Auto Task]" in calls[0]["content"]


def test_reconcile_scheduled_jobs_rebuilds_task_jobs_without_touching_other_targets(tmp_path) -> None:
    tools = _make_tools(tmp_path)
    runner = tools["runner"]
    cron_service = tools["cron_service"]

    cron_service.add_job(
        name="plain-cron",
        schedule=cron_service.list_jobs(include_disabled=True) or runner.build_schedule(every_seconds=30),
        target_kind="legacy_message",
        target_id="plain",
    )
    runner.create_after_task(
        instruction="提醒用户吃饭",
        after_seconds=120,
        source_session_key="cli:direct",
        channel="cli",
        chat_id="direct",
    )
    cron_service.replace_jobs_for_target_kind("task", [])

    rebuilt = runner.reconcile_scheduled_jobs()
    jobs = cron_service.list_jobs(include_disabled=True)

    assert rebuilt == 1
    assert len([job for job in jobs if job.payload.target_kind == "task"]) == 1
    assert len([job for job in jobs if job.payload.target_kind == "legacy_message"]) == 1


def test_task_runner_scheduler_owner_is_singleton_per_instance(tmp_path) -> None:
    tools_a = _make_tools(tmp_path)
    tools_b = _make_tools(tmp_path)

    import nomi.tasks.runner as task_runner_module

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    original_get_logs_dir = task_runner_module.get_logs_dir
    task_runner_module.get_logs_dir = lambda: logs_dir
    try:
        owner_a = tools_a["runner"].start_scheduler()
        owner_b = tools_b["runner"].start_scheduler()
    finally:
        task_runner_module.get_logs_dir = original_get_logs_dir

    assert owner_a is True
    assert owner_b is False


async def test_scheduled_task_enqueues_global_reminder_for_running_consumers(tmp_path) -> None:
    tools = _make_tools(tmp_path)
    runner = tools["runner"]
    runner._reminders = runner._reminders.__class__(tmp_path / "tasks-runtime" / "reminders.json")
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "channels-service.json").write_text(
        '{"owner":"weixin","pid":123,"mode":"foreground"}',
        encoding="utf-8",
    )
    (logs_dir / "remote-service.json").write_text(
        '{"pid":456,"mode":"foreground"}',
        encoding="utf-8",
    )

    import nomi.tasks.runner as task_runner_module

    original_get_logs_dir = task_runner_module.get_logs_dir
    task_runner_module.get_logs_dir = lambda: logs_dir
    try:
        task = runner.create_after_task(
            instruction="提醒用户吃饭",
            after_seconds=60,
            source_session_key="desktop:test-session",
            channel="desktop",
            chat_id="test-session",
        )

        async def _fake_process_direct_result(
            content,
            session_key,
            channel,
            chat_id,
            history_session_key=None,
            on_progress=None,
            persist_session=True,
        ):
            del content, session_key, channel, chat_id, history_session_key, on_progress, persist_session
            return SimpleNamespace(final_content="该吃饭啦")

        runner._loop.process_direct_result = _fake_process_direct_result
        await runner._run_scheduled(task)
    finally:
        task_runner_module.get_logs_dir = original_get_logs_dir

    remote_pending = runner.list_pending_reminders("remote")
    weixin_pending = runner.list_pending_reminders("weixin")
    assert len(remote_pending) == 1
    assert len(weixin_pending) == 1
    assert remote_pending[0].content == "该吃饭啦"
    assert weixin_pending[0].task_id == task.id
    stored = runner.get_task(task.id)
    assert stored is not None
    assert stored.run.status == "delivered"
    assert stored.run.run_count == 1


@pytest.mark.asyncio
async def test_loop_poll_global_reminders_routes_to_channel_latest_session(tmp_path) -> None:
    tools = _make_tools(tmp_path)
    runner = tools["runner"]
    runner._reminders = runner._reminders.__class__(tmp_path / "tasks-runtime" / "reminders.json")
    loop = runner._loop
    loop.reminder_consumer = "weixin"
    loop.bus = MessageBus()
    loop.tasks = runner
    loop.sessions = SessionManager(tmp_path / "session-workspace")
    loop.sessions.create_session("weixin:wx-user", source="weixin")
    loop._find_latest_session_for_channel = lambda channel: next(
        (
            item["session_id"]
            for item in loop.sessions.list_sessions()
            if item["session_id"].startswith(f"{channel}:")
        ),
        None,
    )
    runner._reminders.enqueue(
        task_id="task_1",
        session_id="desktop:test-session",
        content="全局提醒",
        targets=["weixin"],
    )

    messages: list[OutboundMessage] = []
    original_publish = loop.bus.publish_outbound

    async def _capture(message: OutboundMessage) -> None:
        messages.append(message)

    loop.bus.publish_outbound = _capture
    try:
        from nomi.agent.loop import AgentLoop

        published = await AgentLoop.poll_global_reminders(loop)
    finally:
        loop.bus.publish_outbound = original_publish

    assert published is True
    assert len(messages) == 1
    assert messages[0].channel == "weixin"
    assert messages[0].chat_id == "wx-user"
    assert messages[0].metadata["_task_delivery_id"] == "task_1"


async def test_run_agent_task_keeps_prepare_stage_out_of_main_session(tmp_path) -> None:
    tools = _make_tools(tmp_path)
    runner = tools["runner"]
    task = runner.create_task(
        instruction="生成 AI 日报",
        schedule=runner.build_schedule(at="2099-04-29T09:30:00"),
        turn=1,
        mode="prepared_delivery",
        source_session_key="weixin:wx-user",
        channel="weixin",
        chat_id="wx-user",
    )

    calls: list[str] = []

    async def _fake_process_direct_result(
        content,
        session_key,
        channel,
        chat_id,
        history_session_key=None,
        on_progress=None,
        persist_session=True,
    ):
        del content, channel, chat_id, on_progress
        calls.append(f"{session_key}|{history_session_key}|{persist_session}")
        return SimpleNamespace(final_content="准备好的日报")

    runner._loop.process_direct_result = _fake_process_direct_result
    await runner._run_agent_task(task, stage="prepare", use_source_session_history=True)

    assert calls == [f"task:{task.id}:prepare|weixin:wx-user|False"]


async def test_scheduled_task_timeout_marks_task_failed_and_finishes_state(tmp_path) -> None:
    tools = _make_tools(tmp_path)
    runner = tools["runner"]
    runner._task_execution_timeout_seconds = 1
    task = runner.create_after_task(
        instruction="提醒用户吃饭",
        after_seconds=60,
        source_session_key="desktop:test-session",
        channel="desktop",
        chat_id="test-session",
    )

    async def _stuck_process_direct_result(*_args, **_kwargs):
        await asyncio.sleep(2)
        return SimpleNamespace(final_content="never")

    import asyncio

    runner._loop.process_direct_result = _stuck_process_direct_result
    await runner._run_scheduled(task)

    stored = runner.get_task(task.id)
    assert stored is not None
    assert stored.run.status == "failed"
    assert "timed out" in str(stored.run.error)
    assert stored.run.run_count == 1
    assert stored.run.last_run_at_ms is not None


def test_reconcile_recovers_stale_running_one_shot_task_without_live_cron(tmp_path) -> None:
    tools = _make_tools(tmp_path)
    runner = tools["runner"]
    task = runner.create_after_task(
        instruction="提醒用户吃饭",
        after_seconds=60,
        source_session_key="desktop:test-session",
        channel="desktop",
        chat_id="test-session",
    )
    task.run.status = "running"
    task.run.run_count = 0
    runner.store.update_task(task)
    runner._cron.clear_all()

    runner.reconcile_scheduled_jobs()

    stored = runner.get_task(task.id)
    assert stored is not None
    assert stored.run.status == "failed"
    assert "stale running task" in str(stored.run.error)
    assert stored.run.run_count == 1


async def test_scheduled_task_without_consumers_still_finishes_delivery(tmp_path) -> None:
    tools = _make_tools(tmp_path)
    runner = tools["runner"]
    runner._reminders = runner._reminders.__class__(tmp_path / "tasks-runtime" / "reminders.json")
    logs_dir = tmp_path / "logs-empty"
    logs_dir.mkdir(parents=True, exist_ok=True)
    task = runner.create_after_task(
        instruction="提醒用户吃饭",
        after_seconds=60,
        source_session_key="desktop:test-session",
        channel="desktop",
        chat_id="test-session",
    )

    async def _fake_process_direct_result(*_args, **_kwargs):
        return SimpleNamespace(final_content="该吃饭啦")

    import nomi.tasks.runner as task_runner_module

    original_get_logs_dir = task_runner_module.get_logs_dir
    task_runner_module.get_logs_dir = lambda: logs_dir
    try:
        runner._loop.process_direct_result = _fake_process_direct_result
        await runner._run_scheduled(task)
    finally:
        task_runner_module.get_logs_dir = original_get_logs_dir

    stored = runner.get_task(task.id)
    assert stored is not None
    assert stored.run.status == "delivered"


@pytest.mark.asyncio
async def test_process_message_result_can_borrow_history_without_persisting_session(tmp_path) -> None:
    config = Config()

    async def _dispatch_stub(*_args, **_kwargs):
        return None

    async def _consolidate_stub(*_args, **_kwargs):
        return None

    loop_stub = type(
        "LoopStub",
        (),
        {
            "sessions": SessionManager(tmp_path / "session-workspace"),
            "auto_compact": type(
                "AutoCompactStub",
                (),
                {"prepare_session": staticmethod(lambda session, _key: (session, None))},
            )(),
            "turn_journals": type(
                "TurnJournalStub",
                (),
                {
                    "save": staticmethod(lambda *_args, **_kwargs: None),
                    "get": staticmethod(lambda *_args, **_kwargs: None),
                    "create": staticmethod(
                        lambda session_key: TurnJournalRecord(
                            turn_id="turn_test",
                            session_key=session_key,
                        )
                    ),
                    "maybe_load_from_session": staticmethod(lambda *_args, **_kwargs: None),
                    "delete": staticmethod(lambda *_args, **_kwargs: None),
                },
            )(),
            "user_profile": type(
                "UserProfileStub",
                (),
                {
                    "detect_quick_action": staticmethod(lambda **_kwargs: None),
                    "should_attempt_extraction": staticmethod(lambda **_kwargs: False),
                },
            )(),
            "commands": type(
                "CommandsStub",
                (),
                {"dispatch": staticmethod(_dispatch_stub)},
            )(),
            "consolidator": type(
                "ConsolidatorStub",
                (),
                {"maybe_consolidate_by_tokens": staticmethod(_consolidate_stub)},
            )(),
            "_clear_interrupt_state": staticmethod(lambda *_args, **_kwargs: None),
            "_schedule_background": staticmethod(lambda *_args, **_kwargs: None),
            "_set_tool_context": staticmethod(lambda *_args, **_kwargs: None),
            "_build_command_context": staticmethod(lambda **_kwargs: None),
            "_strip_think": staticmethod(lambda text: text),
            "_tool_hint": staticmethod(lambda _tool_calls: ""),
                "context": type(
                    "CtxStub",
                    (),
                    {
                        "build_messages": staticmethod(
                            lambda **kwargs: [{"role": "history", "content": str(len(kwargs["history"]))}]
                        )
                    },
                )(),
                "skill_registry": type(
                    "SkillRegistryStub",
                    (),
                    {
                        "scan": staticmethod(lambda: []),
                        "record_usage": staticmethod(lambda *_args, **_kwargs: None),
                    },
                )(),
                "runner": None,
                "provider": None,
                "model": "test-model",
            "max_iterations": 1,
            "max_tool_result_chars": 1000,
            "context_window_tokens": 1024,
            "context_block_limit": None,
            "provider_retry_mode": "standard",
            "workspace": tmp_path,
            "tools": type("ToolsStub", (), {"get_definitions": staticmethod(lambda: [])})(),
            "_extra_hooks": [],
            "config": config,
        },
    )()
    processor = TurnProcessor(loop_stub)  # type: ignore[arg-type]
    source = loop_stub.sessions.get_or_create("desktop:source")
    source.add_message("user", "旧消息")
    source.add_message("assistant", "旧回复")
    loop_stub.sessions.save(source)

    captured: dict[str, object] = {}

    async def _fake_run_agent_loop(initial_messages, **_kwargs):
        captured["initial_messages"] = initial_messages
        return ("任务结果", [], [{"role": "assistant", "content": "任务结果"}], "completed", False, False)

    processor.run_agent_loop = _fake_run_agent_loop  # type: ignore[method-assign]

    result = await processor.process_message_result(
        InboundMessage(
            channel="desktop",
            sender_id="user",
            chat_id="target",
            content="[Auto Task]",
            session_key_override="task:test:run",
        ),
        session_key="task:test:run",
        history_session_key="desktop:source",
        persist_session=False,
    )

    assert result.final_content == "任务结果"
    assert captured["initial_messages"] == [{"role": "history", "content": "2"}]
