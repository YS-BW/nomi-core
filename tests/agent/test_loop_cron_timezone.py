from __future__ import annotations

from unittest.mock import MagicMock

from nomi.agent.loop import AgentLoop
from nomi.agent.tools.tasks import TaskCreateAfterTool
from nomi.bus.queue import MessageBus


def test_agent_loop_registers_task_tools_with_default_timezone(tmp_path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        timezone="Asia/Shanghai",
    )

    tool = loop.tools.get("task_create_after")
    assert isinstance(tool, TaskCreateAfterTool)
    assert tool._default_timezone == "Asia/Shanghai"
    assert loop.cron_service.default_timezone == "Asia/Shanghai"
