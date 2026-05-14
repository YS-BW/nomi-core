"""实例关系模型与工具测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from nomi.agent.tools.instance_relations import (
    InstanceInviteCodeTool,
    InstanceInviteTool,
    InstanceRelationAcceptTool,
    InstanceRelationListTool,
    InstanceRelationRejectTool,
    InstanceRelationRenameTool,
    InstanceSendMessageTool,
    InstanceSessionGetTool,
    InstanceSessionListTool,
)
from nomi.instance_channel.invite import build_invite_code, parse_invite_code
from nomi.instance_channel.manager import InstanceRelationManager
from nomi.instance_channel.notification import NotificationService
from nomi.instance_channel.store import (
    InstanceInviteStore,
    InstanceRelationRequestStore,
    InstanceRelationStore,
)


def test_invite_code_round_trip() -> None:
    """邀请码应能稳定编解码。"""
    code = build_invite_code(
        key="default",
        url="http://127.0.0.1:8765/",
        invite_id="inv-1",
        secret="secret-1",
    )

    parsed = parse_invite_code(code)

    assert parsed == {
        "v": "1",
        "key": "default",
        "url": "http://127.0.0.1:8765",
        "invite_id": "inv-1",
        "secret": "secret-1",
    }


def test_invite_store_empty_payload_returns_none(tmp_path) -> None:
    """邀请码文件不存在或为空时应返回 None，而不是抛出 key 校验错误。"""
    store = InstanceInviteStore(tmp_path / "instance-invite.json")

    assert store.get() is None


def test_relation_manager_invite_request_relation_lifecycle(tmp_path) -> None:
    """关系管理器应维护一次性邀请码、pending 申请和已接受关系。"""
    manager = InstanceRelationManager(
        invite_store=InstanceInviteStore(tmp_path / "instance-invite.json"),
        request_store=InstanceRelationRequestStore(tmp_path / "instance-requests.json"),
        relation_store=InstanceRelationStore(tmp_path / "instance-relations.json"),
    )

    first, first_secret = manager.build_invite(key="default", url="http://127.0.0.1:8765")
    second, second_secret = manager.build_invite(key="default", url="http://127.0.0.1:8765")
    with pytest.raises(PermissionError):
        manager.consume_invite(invite_id=first.invite_id, secret=first_secret)
    used = manager.consume_invite(invite_id=second.invite_id, secret=second_secret)
    assert used.used_at_ms is not None
    with pytest.raises(PermissionError):
        manager.consume_invite(invite_id=second.invite_id, secret=second_secret)

    request = manager.create_incoming_request(
        key="xmy",
        url="http://127.0.0.1:8766",
        requested_permission="task",
        response_token="response-token",
        invite_id=second.invite_id,
    )
    assert request.direction == "incoming"
    assert request.requested_permission == "task"
    with pytest.raises(ValueError):
        manager.require_permission("xmy", "chat")

    request, accepted = manager.accept_incoming("xmy", "task")
    assert request.key == "xmy"
    assert accepted.permission == "task"
    assert accepted.relation_id
    assert accepted.relation_token
    assert manager.get_request("xmy") is None
    assert manager.require_permission("xmy", "chat").key == "xmy"
    assert manager.require_permission("xmy", "task").key == "xmy"
    with pytest.raises(PermissionError):
        manager.require_permission("xmy", "all")

    renamed = manager.rename("xmy", "小美")
    assert renamed.name == "小美"

    trusted = manager.set_permission("xmy", "all")
    assert trusted.permission == "all"
    assert manager.require_permission("xmy", "all").key == "xmy"

    removed = manager.remove_relation("xmy")
    assert removed.key == "xmy"
    assert manager.get_relation("xmy") is None


def test_relation_manager_outgoing_accept_and_reject(tmp_path) -> None:
    """outgoing 申请接受/拒绝后应删除 pending request。"""
    manager = InstanceRelationManager(
        request_store=InstanceRelationRequestStore(tmp_path / "instance-requests.json"),
        relation_store=InstanceRelationStore(tmp_path / "instance-relations.json"),
    )
    manager.create_outgoing_request(
        key="xmy",
        url="http://127.0.0.1:8766",
        requested_permission="all",
        response_token="response-token",
        invite_id="inv-1",
    )
    relation = manager.accept_outgoing(
        key="xmy",
        url="http://127.0.0.1:8766",
        relation_id="rel-1",
        relation_token="relation-token",
    )

    assert relation.permission == "chat"
    assert manager.get_request("xmy") is None
    assert manager.require_by_relation_token(
        relation_id="rel-1",
        token="relation-token",
    ).key == "xmy"

    manager.create_outgoing_request(
        key="bomi",
        url="http://127.0.0.1:8767",
        requested_permission="chat",
        response_token="response-token-b",
        invite_id="inv-2",
    )
    assert manager.reject_outgoing("bomi") is True
    assert manager.get_relation("bomi") is None


def test_notification_service_uses_global_reminder_queue() -> None:
    """NotificationService 应复用当前全局提醒队列。"""
    calls = []
    runner = SimpleNamespace(
        enqueue_global_reminder=lambda **kwargs: calls.append(kwargs) or True
    )
    service = NotificationService(runner)

    assert service.enqueue_global(notification_id="relation:xmy", content="hello") is True
    assert calls == [
        {
            "task_id": "relation:xmy",
            "session_id": "instance:notifications",
            "content": "hello",
            "target_channels": [],
        }
    ]


@pytest.mark.asyncio
async def test_instance_tools_call_runtime() -> None:
    """Agent 工具应调用 runtime 的关系能力。"""
    calls = []

    class RuntimeStub:
        def list_instance_relations(self):
            return [
                {
                    "key": "xmy",
                    "name": "小美",
                    "url": "http://127.0.0.1:8766",
                    "status": "friend",
                    "permission": "chat",
                }
            ]

        def build_instance_invite_code(self, public_url=None):
            calls.append(("invite_code", public_url))
            return "nomi://instance-invite?token=t"

        async def invite_instance(self, *, invite_code, requested_permission="chat"):
            calls.append(("invite", invite_code, requested_permission))
            return {"ok": True, "key": "xmy"}

        async def accept_instance_relation(self, key, permission):
            calls.append(("accept", key, permission))
            return {"key": key, "permission": permission}

        async def reject_instance_relation_async(self, key):
            calls.append(("reject", key))
            return True

        def rename_instance_relation(self, key, name):
            calls.append(("rename", key, name))
            return {"key": key, "name": name}

        async def remove_instance_relation(self, key):
            calls.append(("remove", key))
            return {"key": key, "removed": True}

        def set_instance_relation_permission(self, key, permission):
            calls.append(("permission", key, permission))
            return {"key": key, "permission": permission}

        async def send_instance_message(self, key, message):
            calls.append(("send", key, message))
            return {"content": "pong"}

        def list_instance_sessions(self, limit=10):
            calls.append(("session_list", limit))
            return [
                {
                    "key": "xmy",
                    "name": "小美",
                    "status": "friend",
                    "message_count": 2,
                    "updated_at": "2026-05-14T12:00:00",
                }
            ]

        def get_instance_session_messages(self, key, limit=20):
            calls.append(("session_get", key, limit))
            return {
                "key": key,
                "name": "小美",
                "messages": [{"label": "我发给对方", "content": "ping"}],
            }

    runtime = RuntimeStub()

    tool = InstanceInviteCodeTool(runtime)
    assert "public_url" not in tool.parameters["properties"]
    assert "nomi://instance-invite" in await tool.execute()
    assert "已向" in await InstanceInviteTool(runtime).execute(
        invite_code=(
            "nomi://instance-invite?v=1&key=xmy&url=http%3A%2F%2F127.0.0.1%3A8766"
            "&invite_id=inv-1&secret=s"
        ),
        requested_permission="task",
    )
    assert "xmy" in await InstanceRelationListTool(runtime).execute()
    assert "已接受" in await InstanceRelationAcceptTool(runtime).execute(
        key="xmy", permission="chat"
    )
    assert "已拒绝" in await InstanceRelationRejectTool(runtime).execute(key="xmy")
    assert "备注" in await InstanceRelationRenameTool(runtime).execute(key="xmy", name="小美")
    from nomi.agent.tools.instance_relations import (
        InstanceRelationRemoveTool,
        InstanceRelationSetPermissionTool,
    )

    assert "已删除" in await InstanceRelationRemoveTool(runtime).execute(key="xmy")
    assert "权限设置" in await InstanceRelationSetPermissionTool(runtime).execute(
        key="xmy", permission="all"
    )
    assert await InstanceSendMessageTool(runtime).execute(key="xmy", message="ping") == "pong"
    assert "最近 instance 会话" in await InstanceSessionListTool(runtime).execute(limit=5)
    assert "我发给对方" in await InstanceSessionGetTool(runtime).execute(key="xmy", limit=5)
    assert calls == [
        ("invite_code", None),
        (
            "invite",
            "nomi://instance-invite?v=1&key=xmy&url=http%3A%2F%2F127.0.0.1%3A8766&invite_id=inv-1&secret=s",
            "task",
        ),
        ("accept", "xmy", "chat"),
        ("reject", "xmy"),
        ("rename", "xmy", "小美"),
        ("remove", "xmy"),
        ("permission", "xmy", "all"),
        ("send", "xmy", "ping"),
        ("session_list", 5),
        ("session_get", "xmy", 5),
    ]
