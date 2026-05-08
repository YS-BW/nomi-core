from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nomi.agent.loop_runtime.background import BackgroundRuntime
from nomi.cron.types import CronJob, CronJobState, CronPayload, CronSchedule
from nomi.providers.base import LLMProvider


def _mk_loop(tmp_path: Path):
    from nomi.agent.loop import AgentLoop
    from nomi.bus.queue import MessageBus

    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.generation = SimpleNamespace(max_tokens=4096)
    with patch("nomi.agent.loop.register_default_tools"):
        loop = AgentLoop(
            bus=MessageBus(),
            provider=provider,
            workspace=tmp_path,
        )
    return loop


@pytest.mark.asyncio
async def test_background_runtime_delegates_trigger_to_task_runner(tmp_path: Path) -> None:
    loop = _mk_loop(tmp_path)
    runtime = BackgroundRuntime(loop)
    loop.tasks.run_trigger = AsyncMock(return_value=None)

    job = CronJob(
        id="cron_123",
        name="提醒",
        enabled=True,
        schedule=CronSchedule(kind="at", at_ms=9999999999999),
        payload=CronPayload(
            target_kind="task",
            target_id="task_123",
            phase="run",
        ),
        state=CronJobState(),
    )

    await runtime.run_trigger(job)

    loop.tasks.run_trigger.assert_awaited_once_with(job)
