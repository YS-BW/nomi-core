from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from nomi.cron import CronSchedule, CronService


def _future_iso(minutes: int = 5) -> str:
    return (datetime.now().astimezone() + timedelta(minutes=minutes)).isoformat()


def test_cron_service_add_list_remove(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")

    job = service.add_job(
        name="check-news",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        target_kind="task",
        target_id="task_news",
        phase="run",
    )

    jobs = service.list_jobs()
    assert [item.id for item in jobs] == [job.id]
    assert jobs[0].payload.target_kind == "task"
    assert jobs[0].payload.target_id == "task_news"

    assert service.remove_job(job.id) is True
    assert service.list_jobs() == []


def test_cron_service_persists_target_payload(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")

    job = service.add_job(
        name="wechat-reminder",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        target_kind="task",
        target_id="task_reminder",
        phase="deliver",
    )

    assert job.payload.target_kind == "task"
    assert job.payload.target_id == "task_reminder"
    assert job.payload.phase == "deliver"
    loaded = service.get_job(job.id)
    assert loaded is not None
    assert loaded.payload.target_kind == "task"
    assert loaded.payload.target_id == "task_reminder"
    assert loaded.payload.phase == "deliver"


def test_cron_service_reuses_recent_duplicate_job(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")
    schedule = CronSchedule(kind="at", at_ms=int(datetime.fromisoformat(_future_iso()).timestamp() * 1000))

    first = service.add_job(
        name="open-wechat",
        schedule=schedule,
        target_kind="task",
        target_id="task_open_wechat",
        delete_after_run=True,
    )
    second = service.add_job(
        name="open-wechat",
        schedule=schedule,
        target_kind="task",
        target_id="task_open_wechat",
        delete_after_run=True,
    )

    assert second.id == first.id
    assert len(service.list_jobs(include_disabled=True)) == 1


def test_cron_service_rejects_invalid_schedule_inputs(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")

    with pytest.raises(ValueError, match="unknown timezone"):
        service.add_job(
            name="bad-tz",
            schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="Mars/Phobos"),
            target_kind="task",
            target_id="task_bad_tz",
        )

    with pytest.raises(ValueError, match="invalid cron expression"):
        service.add_job(
            name="bad-cron",
            schedule=CronSchedule(kind="cron", expr="not-a-cron", tz="Asia/Shanghai"),
            target_kind="task",
            target_id="task_bad_cron",
        )

    with pytest.raises(ValueError, match="at must be in the future"):
        service.add_job(
            name="past",
            schedule=CronSchedule(kind="at", at_ms=1),
            target_kind="task",
            target_id="task_past",
        )


def test_cron_service_update_job_preserves_id_and_history(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")
    job = service.add_job(
        name="open-wechat",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        target_kind="task",
        target_id="task_open_wechat",
    )
    created_at_ms = job.created_at_ms
    job.state.last_run_at_ms = 123
    job.state.last_status = "ok"
    job.state.run_history = []

    updated = service.update_job(
        job.id,
        name="打开浏览器",
        schedule=CronSchedule(kind="at", at_ms=int(datetime.fromisoformat(_future_iso(10)).timestamp() * 1000)),
        delete_after_run=True,
    )

    assert updated is not None
    assert updated.id == job.id
    assert updated.created_at_ms == created_at_ms
    assert updated.updated_at_ms >= created_at_ms
    assert updated.payload.target_id == "task_open_wechat"
    assert updated.name == "打开浏览器"
    assert updated.schedule.kind == "at"
    assert updated.delete_after_run is True
    assert updated.enabled is True
    assert updated.state.last_run_at_ms == 123
    assert updated.state.last_status == "ok"


def test_cron_service_update_job_returns_none_when_missing(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")

    assert service.update_job("cron_missing", name="hi") is None


@pytest.mark.asyncio
async def test_cron_service_runs_due_job_and_records_state(tmp_path) -> None:
    calls: list[str] = []

    async def _on_job(job) -> None:
        calls.append(job.id)

    service = CronService(
        tmp_path / "cron" / "jobs.json",
        on_job=_on_job,
        default_timezone="Asia/Shanghai",
    )
    job = service.add_job(
        name="once",
        schedule=CronSchedule(kind="at", at_ms=int(datetime.fromisoformat(_future_iso()).timestamp() * 1000)),
        target_kind="task",
        target_id="task_once",
        delete_after_run=True,
    )

    service.start()
    stored = service.get_job(job.id)
    assert stored is not None
    stored.state.next_run_at_ms = 0

    await service.run_due_jobs()
    await service.stop()

    assert calls == [job.id]
    assert service.get_job(job.id) is None


@pytest.mark.asyncio
async def test_cron_service_disables_one_shot_job_when_not_delete_after_run(tmp_path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json", default_timezone="Asia/Shanghai")
    job = service.add_job(
        name="once-keep",
        schedule=CronSchedule(kind="at", at_ms=int(datetime.fromisoformat(_future_iso()).timestamp() * 1000)),
        target_kind="task",
        target_id="task_once_keep",
        delete_after_run=False,
    )

    service.start()
    stored = service.get_job(job.id)
    assert stored is not None
    stored.state.next_run_at_ms = 0

    await service.run_due_jobs()
    await service.stop()

    hidden = service.list_jobs()
    all_jobs = service.list_jobs(include_disabled=True)
    assert hidden == []
    assert len(all_jobs) == 1
    assert all_jobs[0].enabled is False
    assert all_jobs[0].state.last_status == "ok"
    assert len(all_jobs[0].state.run_history) == 1


@pytest.mark.asyncio
async def test_rearming_timer_does_not_cancel_running_due_job(tmp_path) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls: list[str] = []

    async def _on_job(job) -> None:
        calls.append(job.id)
        started.set()
        await release.wait()

    service = CronService(
        tmp_path / "cron" / "jobs.json",
        on_job=_on_job,
        default_timezone="Asia/Shanghai",
    )
    job = service.add_job(
        name="once-no-cancel",
        schedule=CronSchedule(kind="at", at_ms=int(datetime.fromisoformat(_future_iso()).timestamp() * 1000)),
        target_kind="task",
        target_id="task_once_no_cancel",
        delete_after_run=True,
    )

    service.start()
    stored = service.get_job(job.id)
    assert stored is not None
    stored.state.next_run_at_ms = 0

    run_task = asyncio.create_task(service.run_due_jobs())
    await started.wait()

    service._arm_timer()
    assert not run_task.done()

    release.set()
    await run_task
    await service.stop()

    assert calls == [job.id]
    assert service.get_job(job.id) is None
