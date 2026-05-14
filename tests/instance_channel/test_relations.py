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
from nomi.instance_channel.store import InstanceRelationStore


def test_invite_code_round_trip() -> None:
    """邀请码应能稳定编解码。"""
    code = build_invite_code(
        name="default",
        url="http://127.0.0.1:8765/",
        token="nomi-remote-token",
    )

    parsed = parse_invite_code(code)

    assert parsed == {
        "name": "default",
        "url": "http://127.0.0.1:8765",
        "token": "nomi-remote-token",
    }


def test_relation_manager_status_permission_and_rename(tmp_path) -> None:
    """关系管理器应维护 pending/friend/trusted 与备注。"""
    manager = InstanceRelationManager(
        store=InstanceRelationStore(tmp_path / "instance-relations.json")
    )

    pending = manager.upsert_pending(
        key="xmy",
        url="http://127.0.0.1:8766",
        token="token-x",
    )
    assert pending.status == "pending"
    assert pending.permission == "chat"
    with pytest.raises(PermissionError):
        manager.require_permission("xmy", "chat")

    accepted = manager.accept("xmy", "task")
    assert accepted.status == "friend"
    assert accepted.permission == "task"
    assert manager.require_permission("xmy", "chat").key == "xmy"
    assert manager.require_permission("xmy", "task").key == "xmy"
    with pytest.raises(PermissionError):
        manager.require_permission("xmy", "all")

    renamed = manager.rename("xmy", "小美")
    assert renamed.name == "小美"

    trusted = manager.accept("xmy", "all")
    assert trusted.status == "trusted"
    assert trusted.permission == "all"
    assert manager.require_permission("xmy", "all").key == "xmy"

    repeated = manager.upsert_pending(
        key="xmy",
        url="http://127.0.0.1:8766",
        token="token-x",
    )
    assert repeated.status == "trusted"
    assert repeated.permission == "all"
    assert manager.find_relation_by_endpoint("http://127.0.0.1:8766/", "token-x").key == "xmy"


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

        async def invite_instance(self, key, *, url=None, token=None, invite_code=None):
            calls.append(("invite", key, url, token, invite_code))
            return {"ok": True}

        async def accept_instance_relation(self, key, permission):
            calls.append(("accept", key, permission))
            return {"key": key, "permission": permission}

        async def reject_instance_relation_async(self, key):
            calls.append(("reject", key))
            return True

        def rename_instance_relation(self, key, name):
            calls.append(("rename", key, name))
            return {"key": key, "name": name}

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

    assert "nomi://instance-invite" in await InstanceInviteCodeTool(runtime).execute(
        public_url="http://127.0.0.1:8765"
    )
    assert "已向" in await InstanceInviteTool(runtime).execute(
        key="xmy",
        invite_code="nomi://instance-invite?token=t",
    )
    assert "xmy" in await InstanceRelationListTool(runtime).execute()
    assert "已接受" in await InstanceRelationAcceptTool(runtime).execute(
        key="xmy", permission="chat"
    )
    assert "已拒绝" in await InstanceRelationRejectTool(runtime).execute(key="xmy")
    assert "备注" in await InstanceRelationRenameTool(runtime).execute(key="xmy", name="小美")
    assert await InstanceSendMessageTool(runtime).execute(key="xmy", message="ping") == "pong"
    assert "最近 instance 会话" in await InstanceSessionListTool(runtime).execute(limit=5)
    assert "我发给对方" in await InstanceSessionGetTool(runtime).execute(key="xmy", limit=5)
    assert calls == [
        ("invite_code", "http://127.0.0.1:8765"),
        ("invite", "xmy", None, None, "nomi://instance-invite?token=t"),
        ("accept", "xmy", "chat"),
        ("reject", "xmy"),
        ("rename", "xmy", "小美"),
        ("send", "xmy", "ping"),
        ("session_list", 5),
        ("session_get", "xmy", 5),
    ]
