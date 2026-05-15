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
        self.notification_content = "pong"

    async def _process_direct_result(self, content: str, **kwargs) -> SimpleNamespace:
        """模拟 AgentLoop 处理消息并写入 session。"""
        session_key = kwargs.get("session_key") or "instance:xmy"
        session = self.sessions.get_or_create(session_key)
        session.add_message("user", content)
        session.add_message("assistant", "pong")
        self.sessions.save(session)
        return SimpleNamespace(
            session_key=session_key,
            final_content=self.notification_content,
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


class _QuickActionLoopStub(_LoopStub):
    """测试 runtime 初始化时绑定的快捷动作 handler。"""

    def __init__(self, workspace: Path) -> None:
        """初始化测试用 AgentLoop stub。"""
        super().__init__(workspace)
        self.tasks = SimpleNamespace(enqueue_global_reminder=lambda **_kwargs: True)
        self.registered_tools = []
        self.tools = SimpleNamespace(
            register=lambda tool: self.registered_tools.append(tool.name),
        )
        self.instance_relation_quick_action_handler = None


class _InstanceClientStub:
    """测试用 instance channel client。"""

    def __init__(self) -> None:
        """初始化调用记录。"""
        self.requests: list[tuple[object, dict]] = []
        self.responses: list[tuple[object, dict]] = []
        self.removes: list[tuple[object, dict]] = []
        self.messages: list[tuple[object, dict]] = []
        self.message_result: dict = {"ok": True, "content": "remote pong"}

    async def send_relation_request(
        self,
        *,
        url: str,
        invite_id: str,
        secret: str,
        payload: dict,
    ) -> dict:
        """记录关系申请。"""
        self.requests.append(({"url": url, "invite_id": invite_id, "secret": secret}, payload))
        return {"ok": True}

    async def send_relation_response(self, request, payload: dict) -> dict:
        """记录关系响应。"""
        self.responses.append((request, payload))
        return {"ok": True}

    async def send_relation_remove(self, relation, payload: dict) -> dict:
        """记录关系删除通知。"""
        self.removes.append((relation, payload))
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


def _create_incoming_request(
    runtime: NomiRuntime,
    key: str = "xmy",
    *,
    url: str = "http://127.0.0.1:8766",
    requested_permission: str = "chat",
    response_token: str = "response-token",
    invite_id: str = "inv-1",
):
    """创建测试用 incoming pending 申请。"""
    return runtime.instance_relations.create_incoming_request(
        key=key,
        url=url,
        requested_permission=requested_permission,
        response_token=response_token,
        invite_id=invite_id,
    )


def _create_outgoing_request(
    runtime: NomiRuntime,
    key: str = "xmy",
    *,
    url: str = "http://127.0.0.1:8766",
    requested_permission: str = "chat",
    response_token: str = "response-token",
    invite_id: str = "inv-1",
):
    """创建测试用 outgoing pending 申请。"""
    return runtime.instance_relations.create_outgoing_request(
        key=key,
        url=url,
        requested_permission=requested_permission,
        response_token=response_token,
        invite_id=invite_id,
    )


def _create_relation(
    runtime: NomiRuntime,
    key: str = "xmy",
    *,
    url: str = "http://127.0.0.1:8766",
    permission: str = "chat",
):
    """创建测试用已接受关系。"""
    return runtime.instance_relations.create_relation(key=key, url=url, permission=permission)


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
    relation = _create_relation(runtime)

    result = await runtime.receive_instance_message(
        {"from_key": "xmy", "content": "ping"},
        relation_id=relation.relation_id,
        relation_token=relation.relation_token,
    )

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
        allowed_tool_names=runtime.instance_inbound_allowed_tool_names("chat"),
    )
    session = runtime.agent_loop.sessions.get("instance:xmy")
    assert session is not None
    assert session.metadata["source"] == "instance"
    assert session.messages[-2]["metadata"]["direction"] == "inbound"
    assert session.messages[-2]["metadata"]["actor"] == "remote_instance"
    assert session.messages[-1]["metadata"]["direction"] == "outbound"
    assert session.messages[-1]["metadata"]["actor"] == "self_instance"


@pytest.mark.asyncio
async def test_runtime_instance_relation_quick_action_accepts_single_pending_trust(
    tmp_path: Path,
) -> None:
    """用户只回复“信任”时，唯一 pending 关系应被接受为 all 权限。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    config.remote.host = "127.0.0.1"
    config.remote.port = 8765
    config.remote.auth_token = "token-default"
    loop_stub = _QuickActionLoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    client = _InstanceClientStub()
    runtime.instance_relations.client = client
    _create_incoming_request(runtime, requested_permission="task")

    result = await runtime.handle_instance_relation_quick_action("信任")

    assert result == "已信任 xmy，权限：all。"
    relation = runtime.instance_relations.get_relation("xmy")
    assert relation is not None
    assert relation.permission == "all"
    assert client.responses[0][1]["status"] == "accepted"
    assert client.responses[0][1]["permission"] == "all"
    assert client.responses[0][1]["relation_id"] == relation.relation_id
    assert runtime.instance_relations.get_request("xmy") is None


@pytest.mark.asyncio
async def test_runtime_instance_relation_quick_action_rejects_single_pending(
    tmp_path: Path,
) -> None:
    """用户只回复“拒绝”时，唯一 pending 关系应被拒绝并删除。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _QuickActionLoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    client = _InstanceClientStub()
    runtime.instance_relations.client = client
    _create_incoming_request(runtime)

    result = await runtime.handle_instance_relation_quick_action("拒绝")

    assert result == "已拒绝 xmy。"
    assert runtime.instance_relations.get_relation("xmy") is None
    assert runtime.instance_relations.get_request("xmy") is None
    assert client.responses[0][1]["status"] == "rejected"


@pytest.mark.asyncio
async def test_runtime_instance_relation_quick_action_requires_key_for_multiple_pending(
    tmp_path: Path,
) -> None:
    """多个 pending 关系存在时，短回复不能猜测目标。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _QuickActionLoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    _create_incoming_request(runtime, key="xmy")
    _create_incoming_request(runtime, key="bomi", url="http://127.0.0.1:8767")

    result = await runtime.handle_instance_relation_quick_action("同意")

    assert result is not None
    assert "多个待确认" in result
    assert runtime.instance_relations.get_request("xmy") is not None
    assert runtime.instance_relations.get_request("bomi") is not None


@pytest.mark.asyncio
async def test_runtime_instance_relation_quick_action_accepts_named_pending(
    tmp_path: Path,
) -> None:
    """带 key 的确认语句应命中指定 pending 关系。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _QuickActionLoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    runtime.instance_relations.client = _InstanceClientStub()
    _create_incoming_request(runtime, key="xmy")
    _create_incoming_request(runtime, key="bomi", url="http://127.0.0.1:8767")

    result = await runtime.handle_instance_relation_quick_action("同意添加 xmy")

    assert result == "已接受 xmy，权限：chat。"
    assert runtime.instance_relations.get_relation("xmy") is not None
    assert runtime.instance_relations.get_request("bomi") is not None


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
    _create_relation(runtime)

    result = await runtime.send_instance_message("xmy", "ping")

    assert result["content"] == "remote pong"
    assert result["session_id"] == "instance:xmy"
    assert client.messages[0][1]["from_key"] == "nomi"
    assert "from_token" not in client.messages[0][1]
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
    _create_relation(runtime)

    with pytest.raises(RuntimeError, match="boom"):
        await runtime.send_instance_message("xmy", "ping")

    session = runtime.agent_loop.sessions.get("instance:xmy")
    assert session is not None
    assert session.messages[-1]["metadata"]["direction"] == "error"
    assert "boom" in session.messages[-1]["content"]


@pytest.mark.asyncio
async def test_runtime_receive_instance_message_rejects_wrong_relation_token(
    tmp_path: Path,
) -> None:
    """收消息时必须使用 relation token，remote token 不再可用。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    relation = _create_relation(runtime, key="alias")

    with pytest.raises(PermissionError):
        await runtime.receive_instance_message(
            {"from_key": "remote-name", "content": "ping"},
            relation_id=relation.relation_id,
            relation_token="wrong-token",
        )

    loop_stub.process_direct_result.assert_not_awaited()


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
    _create_relation(runtime)
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
    assert messages["messages"][0]["label"] == "我发给对方"


def test_runtime_instance_allowed_tool_names_follow_permission(tmp_path: Path) -> None:
    """instance 权限应映射到明确工具白名单。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(config.workspace_path)
    loop_stub.tools = SimpleNamespace(
        tool_names=["mcp_demo"],
        register=lambda _tool: None,
    )
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )

    chat = runtime.instance_allowed_tool_names("chat")
    task = runtime.instance_allowed_tool_names("task")
    all_tools = runtime.instance_allowed_tool_names("all")

    assert "instance_send_message" in chat
    assert "instance_session_list" in chat
    assert "instance_session_get" in chat
    assert "instance_ask_user" not in chat
    assert "instance_user_request_list" not in chat
    assert "instance_user_request_get" not in chat
    assert "instance_relation_set_permission" not in chat
    assert "instance_set_name" not in chat
    assert "task_create_after" not in chat
    assert "task_create_after" in task
    assert "exec" not in task
    assert "exec" in all_tools
    assert "install_skill" in all_tools
    assert "instance_relation_set_permission" in all_tools
    assert "instance_set_name" in all_tools
    assert "mcp_demo" in all_tools


def test_runtime_registers_instance_set_name_tool(tmp_path: Path) -> None:
    """runtime 初始化时应注册实例改名工具。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _QuickActionLoopStub(config.workspace_path)

    NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )

    assert "instance_set_name" in loop_stub.registered_tools


def test_runtime_invite_code_rejects_wrong_loopback_override(tmp_path: Path) -> None:
    """模型不能把同机其它实例端口写进当前实例的邀请码。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    config.remote.host = "127.0.0.1"
    config.remote.port = 8766
    loop_stub = _LoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )

    with pytest.raises(ValueError, match="does not match this instance remote port"):
        runtime.build_instance_invite_code("http://127.0.0.1:8765")


@pytest.mark.asyncio
async def test_runtime_invite_code_keeps_local_key_and_uses_remote_name_as_note(
    tmp_path: Path,
) -> None:
    """使用邀请码发起申请时应读取对方 key 并写入 outgoing request。"""
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
        "nomi://instance-invite?v=1&key=xmy&url=http%3A%2F%2F127.0.0.1%3A8766"
        "&invite_id=inv-1&secret=secret-1"
    )

    await runtime.invite_instance(invite_code=code, requested_permission="task")

    request = runtime.instance_relations.get_request("xmy")
    assert request is not None
    assert request.direction == "outgoing"
    assert request.requested_permission == "task"
    assert client.requests[0][0]["invite_id"] == "inv-1"
    assert client.requests[0][0]["secret"] == "secret-1"
    assert client.requests[0][1]["from_key"] == "nomi"
    assert client.requests[0][1]["requested_permission"] == "task"


@pytest.mark.asyncio
async def test_runtime_relation_request_notification_uses_agent_generated_text(
    tmp_path: Path,
) -> None:
    """收到好友申请后应把本机模型生成的提醒投递给用户。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    config.remote.host = "127.0.0.1"
    config.remote.port = 8765
    loop_stub = _LoopStub(config.workspace_path)
    loop_stub.notification_content = "xmy 想加你为好友，要不要看看？"
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    notification = _NotificationStub()
    runtime.instance_relations.notification = notification
    invite, secret = runtime.instance_relations.build_invite(
        key="default",
        url="http://127.0.0.1:8765",
    )

    result = await runtime.receive_instance_relation_request(
        {
            "from_key": "xmy",
            "from_url": "http://127.0.0.1:8766",
            "requested_permission": "chat",
            "response_token": "response-token",
        },
        invite_id=invite.invite_id,
        invite_secret=secret,
    )

    assert result == {"ok": True, "status": "pending", "key": "xmy"}
    loop_stub.process_direct_result.assert_awaited_once()
    _, kwargs = loop_stub.process_direct_result.await_args
    assert kwargs["session_key"] == "instance:notifications"
    assert kwargs["channel"] == "instance"
    assert kwargs["persist_session"] is False
    assert kwargs["allowed_tool_names"] == set()
    assert notification.calls == [
        {
            "notification_id": "instance_relation_request:xmy",
            "content": "xmy 想加你为好友，要不要看看？",
        }
    ]


@pytest.mark.asyncio
async def test_runtime_relation_response_accepts_outgoing_request_with_response_token(
    tmp_path: Path,
) -> None:
    """申请方收到 accepted 后应校验 response token 并写入 relation。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    _create_outgoing_request(runtime, key="xmy", response_token="response-token")

    await runtime.receive_instance_relation_response(
        {
            "from_key": "xmy",
            "from_url": "http://127.0.0.1:8766",
            "status": "accepted",
            "relation_id": "rel-1",
            "relation_token": "relation-token",
        },
        response_token="response-token",
    )

    relation = runtime.instance_relations.get_relation("xmy")
    assert relation is not None
    assert relation.relation_id == "rel-1"
    assert relation.relation_token == "relation-token"
    assert relation.permission == "chat"
    assert runtime.instance_relations.get_request("xmy") is None


@pytest.mark.asyncio
async def test_runtime_relation_accept_notification_uses_agent_generated_text(
    tmp_path: Path,
) -> None:
    """关系通过后应把本机模型生成的提醒投递给用户。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(config.workspace_path)
    loop_stub.notification_content = "xmy 已经加好了。"
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    notification = _NotificationStub()
    runtime.instance_relations.notification = notification
    _create_incoming_request(runtime, key="xmy", requested_permission="all")

    result = await runtime.accept_instance_relation("xmy", "all")

    assert result["key"] == "xmy"
    loop_stub.process_direct_result.assert_awaited_once()
    _, kwargs = loop_stub.process_direct_result.await_args
    assert kwargs["session_key"] == "instance:notifications"
    assert kwargs["channel"] == "instance"
    assert kwargs["persist_session"] is False
    assert kwargs["allowed_tool_names"] == set()
    assert kwargs["metadata"]["_instance_event"] == "relation_accepted"
    assert notification.calls == [
        {
            "notification_id": "instance_relation_accepted:xmy",
            "content": "xmy 已经加好了。",
        }
    ]


@pytest.mark.asyncio
async def test_runtime_relation_accept_notification_falls_back_when_agent_fails(
    tmp_path: Path,
) -> None:
    """关系通过提醒生成失败时应使用短 fallback 文案。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(config.workspace_path)
    loop_stub.process_direct_result.side_effect = RuntimeError("provider failed")
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    notification = _NotificationStub()
    runtime.instance_relations.notification = notification
    _create_incoming_request(runtime, key="xmy", requested_permission="chat")

    await runtime.accept_instance_relation("xmy")

    assert notification.calls == [
        {
            "notification_id": "instance_relation_accepted:xmy",
            "content": "已添加 xmy。",
        }
    ]


@pytest.mark.asyncio
async def test_runtime_withdraw_outgoing_request_deletes_local_and_notifies_peer(
    tmp_path: Path,
) -> None:
    """撤回申请应删除本地 outgoing request 并用 response token 通知对方。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    client = _InstanceClientStub()
    runtime.instance_relations.client = client
    _create_outgoing_request(runtime, key="xmy", response_token="response-token")

    result = await runtime.withdraw_instance_relation_request("xmy")

    assert result["withdrawn"] is True
    assert runtime.instance_relations.get_request("xmy") is None
    assert client.responses[0][0].response_token == "response-token"
    assert client.responses[0][1]["status"] == "withdrawn"


@pytest.mark.asyncio
async def test_runtime_relation_response_withdraws_incoming_request_with_response_token(
    tmp_path: Path,
) -> None:
    """接收方收到 withdrawn 后应校验 response token 并删除 incoming request。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    _create_incoming_request(runtime, key="xmy", response_token="response-token")

    result = await runtime.receive_instance_relation_response(
        {"from_key": "xmy", "status": "withdrawn"},
        response_token="response-token",
    )

    assert result == {"ok": True, "status": "withdrawn", "key": "xmy"}
    assert runtime.instance_relations.get_request("xmy") is None


@pytest.mark.asyncio
async def test_runtime_relation_remove_deletes_local_relation_and_notifies_peer(
    tmp_path: Path,
) -> None:
    """删除关系应物理删除本地 relation 并尽力通知对方。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    loop_stub = _LoopStub(config.workspace_path)
    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: loop_stub,
    )
    client = _InstanceClientStub()
    runtime.instance_relations.client = client
    _create_relation(runtime)

    removed = await runtime.remove_instance_relation("xmy")

    assert removed["removed"] is True
    assert runtime.instance_relations.get_relation("xmy") is None
    assert client.removes[0][1]["status"] == "removed"


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
    config.providers.deepseek.model = "deepseek-chat"
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


def test_runtime_set_instance_key_persists_config_and_soul(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """runtime 改名应同时写回配置和 SOUL.md。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config_path = tmp_path / "config.json"
    save_config(config, config_path)
    monkeypatch.setattr("nomi.runtime.app.get_config_path", lambda: config_path)

    runtime = NomiRuntime.from_config(
        config,
        provider_builder=lambda _config: object(),
        agent_loop_factory=lambda **_kwargs: _LoopStub(config.workspace_path),
    )

    result = runtime.set_instance_key("小美")

    saved = Config.model_validate_json(config_path.read_text(encoding="utf-8"))
    soul = (config.workspace_path / "SOUL.md").read_text(encoding="utf-8")
    assert result["key"] == "小美"
    assert saved.instance.key == "小美"
    assert "我是 小美，一个个人 AI 助手。" in soul


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


def test_runtime_update_provider_can_update_mimo_token_plan_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """update_provider 应支持 MiMo Token Plan key 的写入和清空。"""
    config = Config()
    config.agents.defaults.provider = "mimo"
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

    result = runtime.update_provider("mimo", token_plan_api_key="tp-test")
    saved = Config.model_validate_json(config_path.read_text(encoding="utf-8"))
    assert result["settings"]["api_key_set"] is False
    assert result["settings"]["api_key_preview"] is None
    assert result["requires_runtime_reload"] is True
    assert saved.providers.mimo.token_plan_api_key == "tp-test"

    cleared = runtime.update_provider("mimo", clear_token_plan_api_key=True)
    saved = Config.model_validate_json(config_path.read_text(encoding="utf-8"))
    assert cleared["settings"]["api_key_set"] is False
    assert saved.providers.mimo.token_plan_api_key == ""


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
    config.providers.deepseek.model = "deepseek-chat"
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
    assert runtime.state.config.providers.minimax.model == "MiniMax-M2.7"
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
