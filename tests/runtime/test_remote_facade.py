"""runtime 远程 facade 测试。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nomi.config.schema import Config
from nomi.runtime.app import NomiRuntime
from nomi.session.errors import SessionNotFoundError
from nomi.session.manager import SessionManager


class _LoopStub:
    def __init__(self, workspace: Path) -> None:
        self.sessions = SessionManager(workspace)
        self.process_direct = AsyncMock(return_value="ok")


@pytest.mark.asyncio
async def test_runtime_send_user_message_publishes_streaming_inbound(tmp_path: Path) -> None:
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )

    loop_stub.sessions.create_session("desktop:test")

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


def test_runtime_list_sessions_supports_keyset_pagination(tmp_path: Path) -> None:
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(tmp_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )

    first = runtime.create_session("desktop:a", title="A")
    second = runtime.create_session("desktop:b", title="B")
    third = runtime.create_session("desktop:c", title="C")
    now = datetime.now()
    for offset, session_id in enumerate(("desktop:a", "desktop:c", "desktop:b")):
        session = runtime.agent_loop.sessions.get(session_id)
        assert session is not None
        session.updated_at = now + timedelta(seconds=3 - offset)
        runtime.agent_loop.sessions.save(session)

    result = runtime.list_sessions(page_size=2)
    assert result["total_count"] == 3
    assert len(result["sessions"]) == 2
    assert result["sessions"][0]["session_id"] == "desktop:a"
    assert result["sessions"][1]["session_id"] == "desktop:c"
    assert result["next_page_token"] is not None

    next_page = runtime.list_sessions(page_token=result["next_page_token"], page_size=2)
    assert [item["session_id"] for item in next_page["sessions"]] == ["desktop:b"]

    deleted = runtime.delete_session("desktop:b")
    assert deleted == {"session_id": "desktop:b", "deleted": True}
    assert runtime.load_session_messages("desktop:a", limit=1)["session_id"] == "desktop:a"
    assert runtime.list_sessions()["total_count"] == 2
    assert first["session_id"] == "desktop:a"
    assert second["session_id"] == "desktop:b"
    assert third["session_id"] == "desktop:c"


def test_runtime_missing_session_raises_session_not_found(tmp_path: Path) -> None:
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(tmp_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )

    with pytest.raises(SessionNotFoundError):
        runtime.load_session_messages("desktop:missing", limit=1)
