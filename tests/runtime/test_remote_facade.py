"""runtime 远程 facade 测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nomi.config.schema import Config
from nomi.runtime.app import NomiRuntime
from nomi.session.manager import SessionManager


class _LoopStub:
    def __init__(self, workspace: Path) -> None:
        self.sessions = SessionManager(workspace)
        self.process_direct = AsyncMock(return_value="ok")


@pytest.mark.asyncio
async def test_runtime_send_user_message_publishes_streaming_inbound() -> None:
    config = Config()
    loop_stub = _LoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )

    await runtime.send_user_message(
        "desktop:test",
        "hello",
        client_id="client-1",
        metadata={"foo": "bar"},
    )

    inbound = await asyncio.wait_for(runtime.bus.consume_inbound(), timeout=1.0)
    assert inbound.channel == "desktop"
    assert inbound.chat_id == "test"
    assert inbound.content == "hello"
    assert inbound.metadata["_wants_stream"] is True
    assert inbound.metadata["_session_id"] == "desktop:test"
    assert inbound.metadata["foo"] == "bar"


def test_runtime_load_session_messages_returns_cursor_slice(tmp_path: Path) -> None:
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(tmp_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )

    session = runtime.agent_loop.sessions.get_or_create("desktop:test")
    session.add_message("system", "sys")
    session.add_message("user", "u1")
    session.add_message("assistant", "a1")
    session.add_message("user", "u2")
    runtime.agent_loop.sessions.save(session)

    payload = runtime.load_session_messages("desktop:test", limit=2)

    assert payload["session_id"] == "desktop:test"
    assert payload["total_messages"] == 3
    assert [item["content"] for item in payload["messages"]] == ["a1", "u2"]
    assert payload["next_cursor"] == 1
