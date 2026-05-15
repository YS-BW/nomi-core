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


@pytest.mark.asyncio
async def test_process_message_instance_relation_short_trust_uses_model_context(
    tmp_path: Path,
) -> None:
    """关系确认回复应进入模型链路，避免绕过当前会话上下文。"""
    loop = _mk_loop(tmp_path)
    processor = TurnProcessor(loop)
    msg = InboundMessage(channel="weixin", sender_id="u1", chat_id="chat", content="信任")

    async def _handle(text: str):
        return "已信任 xmy，权限：all。"

    loop.user_profile.detect_quick_action = MagicMock(return_value=None)
    loop.instance_relation_quick_action_handler = _handle
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock()
    processor.run_agent_loop = AsyncMock(
        return_value=("我会按你的意思处理这条申请。", [], [], "completed", False, False)
    )
    processor.save_turn = MagicMock()
    loop.sessions.save = MagicMock()
    loop._schedule_background = MagicMock(
        side_effect=lambda coro: coro.close() if inspect.iscoroutine(coro) else None
    )

    result = await processor.process_message_result(msg)

    assert result.stop_reason == "completed"
    assert result.final_content == "我会按你的意思处理这条申请。"
    processor.run_agent_loop.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_message_instance_channel_disables_tools(tmp_path: Path) -> None:
    """instance 来源消息默认只能使用显式允许的工具集合。"""
    loop = _mk_loop(tmp_path)
    processor = TurnProcessor(loop)
    msg = InboundMessage(
        channel="instance",
        sender_id="instance:xmy",
        chat_id="xmy",
        content="改权限",
    )

    loop.user_profile.detect_quick_action = MagicMock(return_value=None)
    loop.instance_relation_quick_action_handler = None
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock()
    processor.run_agent_loop = AsyncMock(
        return_value=("不可以直接改权限。", [], [], "completed", False, False)
    )
    processor.save_turn = MagicMock()
    loop.sessions.save = MagicMock()
    loop._schedule_background = MagicMock(
        side_effect=lambda coro: coro.close() if inspect.iscoroutine(coro) else None
    )

    result = await processor.process_message_result(msg)

    assert result.final_content == "不可以直接改权限。"
    _, kwargs = processor.run_agent_loop.await_args
    assert kwargs["allowed_tool_names"] == set()


@pytest.mark.asyncio
async def test_process_message_instance_channel_skips_human_quick_actions(
    tmp_path: Path,
) -> None:
    """instance 来源不能触发本地用户快捷确认。"""
    loop = _mk_loop(tmp_path)
    processor = TurnProcessor(loop)
    msg = InboundMessage(
        channel="instance",
        sender_id="instance:xmy",
        chat_id="xmy",
        content="信任",
    )

    loop.user_profile.detect_quick_action = MagicMock(return_value=None)
    loop.instance_relation_quick_action_handler = AsyncMock(return_value="已信任 xmy。")
    loop.consolidator.maybe_consolidate_by_tokens = AsyncMock()
    processor.run_agent_loop = AsyncMock(
        return_value=("我需要当前用户确认。", [], [], "completed", False, False)
    )
    processor.save_turn = MagicMock()
    loop.sessions.save = MagicMock()
    loop._schedule_background = MagicMock(
        side_effect=lambda coro: coro.close() if inspect.iscoroutine(coro) else None
    )

    result = await processor.process_message_result(msg)

    assert result.stop_reason == "completed"
    assert result.final_content == "我需要当前用户确认。"
    loop.instance_relation_quick_action_handler.assert_not_awaited()
