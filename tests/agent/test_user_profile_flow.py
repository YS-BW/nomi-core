from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nomi.agent.execution.processor import TurnProcessor
from nomi.agent.memory.store import UserProfileCandidate
from nomi.bus.events import InboundMessage
from nomi.bus.queue import MessageBus
from nomi.providers.base import LLMProvider


def _mk_loop(tmp_path: Path):
    from nomi.agent.loop import AgentLoop

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
async def test_process_message_appends_profile_reminder(tmp_path: Path) -> None:
    loop = _mk_loop(tmp_path)
    processor = TurnProcessor(loop)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="以后你直接一点")

    candidate = UserProfileCandidate(
        id="user_prof_0001",
        status="pending",
        created_at="",
        updated_at="",
        session_key=msg.session_key,
        source_text="以后你直接一点",
        field="沟通偏好.回复风格",
        operation="set",
        value="直接简洁",
        old_value=None,
        reason="用户明确表达",
        confidence=0.9,
    )

    loop.user_profile.detect_quick_action = MagicMock(return_value=None)
    loop.user_profile.extract_candidates = AsyncMock(return_value=[candidate])
    loop.user_profile.build_reminder = MagicMock(
        return_value=SimpleNamespace(
            text="我注意到一个可能值得记住的画像：沟通偏好.回复风格 = 直接简洁。要不要记到 USER.md？"
        )
    )
    processor.run_agent_loop = AsyncMock(
        return_value=("收到，我后面会更直接一点。", [], [], "completed", False, False)
    )
    processor.save_turn = MagicMock()
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock()
    loop.sessions.save = MagicMock()
    loop._schedule_background = MagicMock(
        side_effect=lambda coro: coro.close() if inspect.iscoroutine(coro) else None
    )

    result = await processor.process_message_result(msg)

    assert "收到，我后面会更直接一点。" in result.final_content
    assert "要不要记到 USER.md" in result.final_content


@pytest.mark.asyncio
async def test_process_message_fast_apply_shortcuts_normal_flow(tmp_path: Path) -> None:
    loop = _mk_loop(tmp_path)
    processor = TurnProcessor(loop)
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="记住")

    candidate = UserProfileCandidate(
        id="user_prof_0001",
        status="pending",
        created_at="",
        updated_at="",
        session_key=msg.session_key,
        source_text="以后你直接一点",
        field="沟通偏好.回复风格",
        operation="set",
        value="直接简洁",
        old_value=None,
        reason="用户明确表达",
        confidence=0.9,
    )
    applied = UserProfileCandidate(
        id="user_prof_0001",
        status="applied",
        created_at="",
        updated_at="",
        session_key=msg.session_key,
        source_text="以后你直接一点",
        field="沟通偏好.回复风格",
        operation="set",
        value="直接简洁",
        old_value=None,
        reason="用户明确表达",
        confidence=0.9,
    )

    loop.user_profile.detect_quick_action = MagicMock(
        return_value=SimpleNamespace(action="apply", candidate=candidate)
    )
    loop.user_profile.apply_candidate = MagicMock(return_value=applied)
    processor.run_agent_loop = AsyncMock()

    result = await processor.process_message_result(msg)

    assert result.stop_reason == "user_profile_quick_action"
    assert "已更新 USER.md" in result.final_content
    processor.run_agent_loop.assert_not_called()
