from __future__ import annotations

from types import SimpleNamespace

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
from nomi.cron import CronService
from nomi.tasks import TaskRunner, TaskStore


def _make_tools(tmp_path):
    loop_stub = type(
        "LoopStub",
        (),
        {
            "context": type("Ctx", (), {"timezone": "Asia/Shanghai"})(),
            "bus": None,
            "tools": type("Tools", (), {"get": lambda *_args, **_kwargs: None})(),
            "process_direct_result": None,
        },
    )()
    cron_service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")
    runner = TaskRunner(
        loop=loop_stub,  # type: ignore[arg-type]
        store=TaskStore(tmp_path / "tasks" / "tasks.json"),
        cron_service=cron_service,
    )
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
        on_progress=None,
        persist_session=True,
    ):
        del on_progress
        calls.append({
            "content": content,
            "session_key": session_key,
            "channel": channel,
            "chat_id": chat_id,
            "persist_session": str(persist_session),
        })
        return SimpleNamespace(final_content="该吃饭啦")

    runner._loop.process_direct_result = _fake_process_direct_result
    await runner._run_agent_task(task, stage="run", write_to_main_session=True)

    assert calls[0]["session_key"] == "weixin:wx-user"
    assert calls[0]["persist_session"] == "True"
    assert "[Auto Task]" in calls[0]["content"]


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
        on_progress=None,
        persist_session=True,
    ):
        del content, channel, chat_id, on_progress
        calls.append(f"{session_key}|{persist_session}")
        return SimpleNamespace(final_content="准备好的日报")

    runner._loop.process_direct_result = _fake_process_direct_result
    await runner._run_agent_task(task, stage="prepare", write_to_main_session=False)

    assert calls == [f"task:{task.id}|False"]

