"""runtime 远程 facade 测试。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nomi.config.loader import save_config
from nomi.config.schema import Config
from nomi.cron.types import CronSchedule
from nomi.runtime.app import NomiRuntime
from nomi.runtime.errors import RuntimeReloadBusyError
from nomi.session.errors import SessionNotFoundError
from nomi.session.manager import SessionManager
from nomi.tasks.models import Task, TaskPayload
from nomi.tasks.store import TaskStore


class _LoopStub:
    def __init__(self, workspace: Path) -> None:
        self.sessions = SessionManager(workspace)
        self.process_direct = AsyncMock(return_value="ok")
        self.process_direct_result = AsyncMock(side_effect=self._process_direct_result)

    async def _process_direct_result(self, content: str, **kwargs) -> SimpleNamespace:
        """模拟 AgentLoop 处理消息并写入 session。"""
        session_key = kwargs.get("session_key") or "instance:xmy"
        session = self.sessions.get_or_create(session_key)
        session.add_message("user", content)
        session.add_message("assistant", "pong")
        self.sessions.save(session)
        return SimpleNamespace(
            session_key=session_key,
            final_content="pong",
            stop_reason="completed",
        )


class _ReloadLoopStub:
    def __init__(self, workspace: Path, provider: object, model: str | None) -> None:
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.sessions = SessionManager(workspace)
        self._control = SimpleNamespace(active_tasks={}, pending_queues={})
        self.stop_calls = 0
        self.close_mcp = AsyncMock(return_value=None)
        self.reminder_consumers: set[str] = set()
        self.reminder_consumer: str | None = None

    async def run(self) -> None:
        return None

    def stop(self) -> None:
        self.stop_calls += 1

    def set_reminder_consumers(self, consumers) -> None:
        self.reminder_consumers = set(consumers)
        self.reminder_consumer = next(iter(sorted(self.reminder_consumers)), None)


class _InstanceClientStub:
    """测试用 instance channel client。"""

    def __init__(self) -> None:
        """初始化调用记录。"""
        self.requests: list[tuple[object, dict]] = []
        self.responses: list[tuple[object, dict]] = []
        self.messages: list[tuple[object, dict]] = []
        self.message_result: dict = {"ok": True, "content": "remote pong"}

    async def send_relation_request(self, relation, payload: dict) -> dict:
        """记录关系申请。"""
        self.requests.append((relation, payload))
        return {"ok": True}

    async def send_relation_response(self, relation, payload: dict) -> dict:
        """记录关系响应。"""
        self.responses.append((relation, payload))
        return {"ok": True}

    async def send_message(self, relation, payload: dict) -> dict:
        """记录实例消息。"""
        self.messages.append((relation, payload))
        return dict(self.message_result)


class _NotificationStub:
    """测试用全局通知记录器。"""

    def __init__(self) -> None:
        """初始化调用记录。"""
        self.calls: list[dict] = []

    def enqueue_global(self, **kwargs) -> bool:
        """记录一次全局通知。"""
        self.calls.append(kwargs)
        return True


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

    runtime.create_session("desktop:a", title="A")
    runtime.create_session("desktop:b", title="B")
    runtime.create_session("desktop:c", title="C")
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


@pytest.mark.asyncio
async def test_runtime_receive_instance_message_uses_instance_identity(tmp_path: Path) -> None:
    """收到 instance 消息时应以 instance 身份进入 AgentLoop。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    runtime.instance_relations.upsert_pending(
        key="xmy",
        url="http://127.0.0.1:8766",
        token="token",
    )
    runtime.instance_relations.accept("xmy", "chat")

    result = await runtime.receive_instance_message({"from_key": "xmy", "content": "ping"})

    assert result["content"] == "pong"
    loop_stub.process_direct_result.assert_awaited_once_with(
        "ping",
        session_key="instance:xmy",
        channel="instance",
        chat_id="xmy",
        sender_id="instance:xmy",
        metadata={
            "_session_id": "instance:xmy",
            "_actor": "instance",
            "_instance_relation_key": "xmy",
            "_instance_direction": "inbound",
            "_instance_peer_key": "xmy",
        },
    )
    session = runtime.agent_loop.sessions.get("instance:xmy")
    assert session is not None
    assert session.metadata["source"] == "instance"
    assert session.messages[-2]["metadata"]["direction"] == "inbound"
    assert session.messages[-2]["metadata"]["actor"] == "remote_instance"
    assert session.messages[-1]["metadata"]["direction"] == "outbound"
    assert session.messages[-1]["metadata"]["actor"] == "self_instance"


@pytest.mark.asyncio
async def test_runtime_send_instance_message_records_sender_session(tmp_path: Path) -> None:
    """发送 instance 消息时发送方也应写入唯一 instance 会话。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    config.remote.auth_token = "local-token"
    loop_stub = _LoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    client = _InstanceClientStub()
    runtime.instance_relations.client = client
    runtime.instance_relations.upsert_pending(
        key="xmy",
        url="http://127.0.0.1:8766",
        token="token",
    )
    runtime.instance_relations.accept("xmy", "chat")

    result = await runtime.send_instance_message("xmy", "ping")

    assert result["content"] == "remote pong"
    assert result["session_id"] == "instance:xmy"
    assert client.messages[0][1]["from_token"] == "local-token"
    session = runtime.agent_loop.sessions.get("instance:xmy")
    assert session is not None
    assert [item["content"] for item in session.messages] == ["ping", "remote pong"]
    assert session.messages[0]["metadata"]["direction"] == "outbound"
    assert session.messages[0]["metadata"]["actor"] == "self_instance"
    assert session.messages[1]["metadata"]["direction"] == "inbound"
    assert session.messages[1]["metadata"]["actor"] == "remote_instance"


@pytest.mark.asyncio
async def test_runtime_send_instance_message_records_error(tmp_path: Path) -> None:
    """HTTP 失败时发送方会话应保留失败记录。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )

    class FailingClient(_InstanceClientStub):
        async def send_message(self, relation, payload: dict) -> dict:
            """模拟发送失败。"""
            raise RuntimeError("boom")

    runtime.instance_relations.client = FailingClient()
    runtime.instance_relations.upsert_pending(
        key="xmy",
        url="http://127.0.0.1:8766",
        token="token",
    )
    runtime.instance_relations.accept("xmy", "chat")

    with pytest.raises(RuntimeError, match="boom"):
        await runtime.send_instance_message("xmy", "ping")

    session = runtime.agent_loop.sessions.get("instance:xmy")
    assert session is not None
    assert session.messages[-1]["metadata"]["direction"] == "error"
    assert "boom" in session.messages[-1]["content"]


@pytest.mark.asyncio
async def test_runtime_receive_instance_message_matches_endpoint_when_key_differs(
    tmp_path: Path,
) -> None:
    """收消息时 from_key 不一致也应能通过 endpoint 命中本地关系。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    runtime.instance_relations.upsert_pending(
        key="alias",
        url="http://127.0.0.1:8766",
        token="token-x",
    )
    runtime.instance_relations.accept("alias", "chat")

    result = await runtime.receive_instance_message(
        {
            "from_key": "remote-name",
            "from_url": "http://127.0.0.1:8766",
            "from_token": "token-x",
            "content": "ping",
        }
    )

    assert result["session_id"] == "instance:alias"
    loop_stub.process_direct_result.assert_awaited_once()
    assert loop_stub.process_direct_result.await_args.kwargs["session_key"] == "instance:alias"
    assert runtime.agent_loop.sessions.get("instance:alias") is not None


def test_runtime_instance_session_queries_format_messages(tmp_path: Path) -> None:
    """instance_session 查询应返回最近唯一会话与可读消息。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    runtime.instance_relations.upsert_pending(
        key="xmy",
        url="http://127.0.0.1:8766",
        token="token",
        name="小美",
    )
    runtime.instance_relations.accept("xmy", "chat")
    runtime._append_instance_session_message(
        "xmy",
        role="user",
        content="ping",
        direction="outbound",
        actor="self_instance",
    )

    sessions = runtime.list_instance_sessions()
    messages = runtime.get_instance_session_messages("xmy")

    assert sessions[0]["key"] == "xmy"
    assert sessions[0]["name"] == "小美"
    assert messages["messages"][0]["label"] == "我发给对方"


@pytest.mark.asyncio
async def test_runtime_invite_code_keeps_local_key_and_uses_remote_name_as_note(
    tmp_path: Path,
) -> None:
    """使用邀请码发起申请时应保留本地 key，并把对方实例名作为备注。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    config.remote.auth_token = "local-token"
    loop_stub = _LoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    client = _InstanceClientStub()
    runtime.instance_relations.client = client
    code = (
        "nomi://instance-invite?name=xmy&url=http%3A%2F%2F127.0.0.1%3A8766&token=token-x"
    )

    await runtime.invite_instance("custom-alias", invite_code=code)

    relation = runtime.instance_relations.get_relation("custom-alias")
    assert relation is not None
    assert relation.name == "xmy"
    assert relation.url == "http://127.0.0.1:8766"
    assert relation.token == "token-x"
    assert runtime.instance_relations.get_relation("xmy") is None
    assert client.requests[0][0].key == "custom-alias"


@pytest.mark.asyncio
async def test_runtime_relation_response_matches_existing_endpoint_when_key_differs(
    tmp_path: Path,
) -> None:
    """对方回调 key 不一致时应优先按 endpoint 命中已有关系，避免重复建表项。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    runtime.instance_relations.upsert_pending(
        key="alias",
        url="http://127.0.0.1:8766",
        token="token-x",
    )

    await runtime.receive_instance_relation_response(
        {
            "from_key": "xmy",
            "from_url": "http://127.0.0.1:8766",
            "from_token": "token-x",
            "status": "friend",
            "permission": "chat",
        }
    )

    relation = runtime.instance_relations.get_relation("alias")
    assert relation is not None
    assert relation.status == "friend"
    assert runtime.instance_relations.get_relation("xmy") is None


@pytest.mark.asyncio
async def test_runtime_existing_friend_request_does_not_notify_again(tmp_path: Path) -> None:
    """已是好友的重复申请不应再次触发确认通知。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    notification = _NotificationStub()
    runtime.instance_relations.notification = notification
    runtime.instance_relations.upsert_pending(
        key="xmy",
        url="http://127.0.0.1:8766",
        token="token-x",
    )
    runtime.instance_relations.accept("xmy", "chat")

    await runtime.receive_instance_relation_request(
        {
            "from_key": "xmy",
            "from_url": "http://127.0.0.1:8766",
            "from_token": "token-x",
        }
    )

    assert notification.calls == []
    assert runtime.instance_relations.get_relation("xmy").status == "friend"


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


def test_runtime_provider_settings_persist_to_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.agents.defaults.provider = "deepseek"
    config.agents.defaults.model = "deepseek-chat"
    config_path = tmp_path / "config.json"
    save_config(config, config_path)
    monkeypatch.setattr("nomi.runtime.app.get_config_path", lambda: config_path)

    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **kwargs: _ReloadLoopStub(
            workspace=kwargs["workspace"],
            provider=kwargs["provider"],
            model=kwargs["model"],
        ),
    )

    result = runtime.set_provider_settings(
        "custom",
        api_key="sk-test",
        api_base="https://example.com/v1",
        model="gpt-4.1",
    )

    saved = Config.model_validate_json(config_path.read_text(encoding="utf-8"))
    assert result["provider"] == "custom"
    assert result["settings"]["saved_model"] == "gpt-4.1"
    assert saved.providers.custom.api_key == "sk-test"
    assert saved.providers.custom.api_base == "https://example.com/v1"
    assert saved.providers.custom.model == "gpt-4.1"


def test_runtime_list_providers_includes_management_fields(tmp_path: Path) -> None:
    """provider 列表应返回可直接用于管理面板的字段。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.providers.custom.api_key = "sk-custom"
    config.providers.custom.api_base = "https://example.com/v1"
    config.providers.custom.model = "gpt-4.1"
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **kwargs: _ReloadLoopStub(
            workspace=kwargs["workspace"],
            provider=kwargs["provider"],
            model=kwargs["model"],
        ),
    )

    result = runtime.list_providers()

    custom = next(item for item in result["providers"] if item["provider"] == "custom")
    assert custom["display_name"] == "Custom"
    assert custom["backend"] == "openai_compat"
    assert custom["api_base_editable"] is True
    assert custom["editable"] is True
    assert custom["deletable"] is False
    assert result["apply_mode"] == "reload_runtime"


def test_runtime_update_provider_can_clear_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """update_provider 应支持显式清空 api_key。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.providers.custom.api_key = "sk-custom"
    config.providers.custom.api_base = "https://example.com/v1"
    config.providers.custom.model = "gpt-4.1"
    config_path = tmp_path / "config.json"
    save_config(config, config_path)
    monkeypatch.setattr("nomi.runtime.app.get_config_path", lambda: config_path)

    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **kwargs: _ReloadLoopStub(
            workspace=kwargs["workspace"],
            provider=kwargs["provider"],
            model=kwargs["model"],
        ),
    )

    result = runtime.update_provider("custom", clear_api_key=True)

    saved = Config.model_validate_json(config_path.read_text(encoding="utf-8"))
    assert result["settings"]["api_key_set"] is False
    assert saved.providers.custom.api_key == ""


def test_runtime_sidebar_serializes_task_target_channels(tmp_path: Path) -> None:
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    task_store = TaskStore(tmp_path / "tasks" / "tasks.json")
    task_store.create_task(
        Task(
            id="",
            title="只发微信",
            execution_type="scheduled",
            enabled=True,
            payload=TaskPayload(instruction="只发微信"),
            source_session_key="desktop:test",
            target_channel="desktop",
            target_chat_id="test",
            schedule=CronSchedule(kind="at", at_ms=9999999999999),
            target_channels=["weixin"],
        )
    )
    runtime.state.agent_loop = SimpleNamespace(
        tasks=SimpleNamespace(
            list_tasks=lambda include_disabled=True: task_store.list_tasks(
                include_disabled=include_disabled
            ),
            next_run_for_task=lambda _task_id: 9999999999999,
        ),
        skill_registry=SimpleNamespace(scan=lambda: []),
    )

    sidebar = runtime.get_sidebar_snapshot()

    assert sidebar["tasks"][0]["targetChannels"] == ["weixin"]


@pytest.mark.asyncio
async def test_runtime_set_active_provider_and_reload_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.agents.defaults.provider = "deepseek"
    config.agents.defaults.model = "deepseek-chat"
    config.providers.minimax.api_key = "sk-minimax"
    config.providers.minimax.model = "MiniMax-M2.7"
    config_path = tmp_path / "config.json"
    save_config(config, config_path)
    monkeypatch.setattr("nomi.runtime.app.get_config_path", lambda: config_path)

    created_loops: list[_ReloadLoopStub] = []

    def _build_loop(**kwargs) -> _ReloadLoopStub:
        loop = _ReloadLoopStub(
            workspace=kwargs["workspace"],
            provider=kwargs["provider"],
            model=kwargs["model"],
        )
        created_loops.append(loop)
        return loop

    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=_build_loop,
    )
    runtime.set_reminder_consumers(["remote", "weixin"])

    changed = runtime.set_active_provider("minimax", model="MiniMax-M2.7")
    reloaded = await runtime.reload_runtime()

    assert changed["active"] == {"provider": "minimax", "model": "MiniMax-M2.7"}
    assert reloaded["active"] == {"provider": "minimax", "model": "MiniMax-M2.7"}
    assert runtime.state.config.agents.defaults.provider == "minimax"
    assert runtime.state.config.agents.defaults.model == "MiniMax-M2.7"
    assert created_loops[-1].model == "MiniMax-M2.7"
    assert created_loops[-1].reminder_consumers == {"remote", "weixin"}


@pytest.mark.asyncio
async def test_runtime_reload_runtime_rejects_when_turn_is_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config_path = tmp_path / "config.json"
    save_config(config, config_path)
    monkeypatch.setattr("nomi.runtime.app.get_config_path", lambda: config_path)

    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **kwargs: _ReloadLoopStub(
            workspace=kwargs["workspace"],
            provider=kwargs["provider"],
            model=kwargs["model"],
        ),
    )

    active_task = SimpleNamespace(done=lambda: False)
    runtime.agent_loop._control.active_tasks["desktop:test"] = [active_task]

    with pytest.raises(RuntimeReloadBusyError):
        await runtime.reload_runtime()
