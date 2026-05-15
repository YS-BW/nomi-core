"""remote HTTP + SSE 服务测试。"""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from nomi.bus.events import OutboundMessage
from nomi.bus.queue import MessageBus
from nomi.config.schema import Config
from nomi.remote.server import RemoteServer
from nomi.runtime.errors import ProviderApiBaseNotEditableError
from nomi.runtime.models import InterruptResult, RuntimeStatusSnapshot
from nomi.session.errors import DuplicateSessionIdError, InvalidPageTokenError, SessionNotFoundError


class _FakeSessions:
    """测试用 session 变更订阅源。"""

    def __init__(self) -> None:
        """初始化订阅列表。"""
        self._callbacks = []

    def subscribe_changes(self, callback):
        """注册 session 变更回调。"""
        self._callbacks.append(callback)

        def _unsubscribe() -> None:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

        return _unsubscribe

    def emit_saved(self, session, new_messages) -> None:
        """触发一次保存事件。"""
        for callback in list(self._callbacks):
            callback("saved", session, new_messages)


class _FakeRuntime:
    """测试用 remote runtime facade。"""

    def __init__(self) -> None:
        """初始化 fake runtime。"""
        self.bus = MessageBus()
        self.agent_loop = SimpleNamespace(sessions=_FakeSessions())
        self.sent_messages: list[tuple[str, str, str, dict | None]] = []
        self.interrupt_calls: list[str] = []
        self.reset_calls: list[str] = []
        now_ms = int(datetime.now().timestamp() * 1000)
        self.sessions: dict[str, dict] = {
            "desktop:test": {
                "key": "desktop:test",
                "session_id": "desktop:test",
                "title": "Test",
                "created_at_ms": now_ms,
                "updated_at_ms": now_ms,
                "message_count": 1,
                "archived": False,
                "source": "desktop",
            }
        }
        self.messages: dict[str, list[dict]] = {
            "desktop:test": [{"role": "user", "content": "hello"}],
        }
        self.sidebar = {"tasks": [], "skills": [], "mcpServers": []}
        self.tasks: dict[str, dict] = {}
        self.task_actions: list[tuple[str, dict]] = []
        self.skill_sources: list[str] = []
        self.uninstalled_skills: list[str] = []
        self.mcp_actions: list[tuple[str, str, dict | None]] = []
        self.clear_calls = 0
        self.provider_state = {
            "providers": [
                {
                    "provider": "deepseek",
                    "display_name": "DeepSeek",
                    "backend": "deepseek",
                    "builtin": True,
                    "editable": True,
                    "deletable": False,
                    "api_key_set": True,
                    "api_key_preview": "…1234",
                    "saved_model": "deepseek-chat",
                    "api_base": "https://api.deepseek.com",
                    "api_base_editable": False,
                    "default_api_base": "https://api.deepseek.com",
                    "source": "config",
                }
            ],
            "active": {"provider": "deepseek", "model": "deepseek-chat"},
            "apply_mode": "reload_runtime",
        }
        self.provider_updates: list[dict] = []
        self.active_provider_updates: list[dict] = []
        self.runtime_reload_calls = 0
        self.instance_calls: list[tuple[str, dict]] = []

    async def create_turn(
        self,
        session_id: str,
        content: str,
        *,
        client_id: str,
        metadata: dict | None = None,
    ) -> dict:
        """创建测试 turn。"""
        await self.send_user_message(session_id, content, client_id=client_id, metadata=metadata)
        return {"turn_id": "turn_fake", "session_id": session_id, "status": "queued"}

    async def send_user_message(
        self,
        session_id: str,
        content: str,
        *,
        client_id: str,
        metadata: dict | None = None,
    ) -> None:
        """记录一条远端消息。"""
        if session_id not in self.sessions:
            raise SessionNotFoundError("session not found", session_id=session_id)
        self.sent_messages.append((session_id, content, client_id, metadata))
        self.messages.setdefault(session_id, []).append({"role": "user", "content": content})
        self.sessions[session_id]["updated_at_ms"] = int(datetime.now().timestamp() * 1000)
        self.sessions[session_id]["message_count"] = len(self.messages[session_id])

    def interrupt_session(self, session_id: str, reason: str = "user_interrupt"):
        """记录中断请求。"""
        if session_id not in self.sessions:
            raise SessionNotFoundError("session not found", session_id=session_id)
        self.interrupt_calls.append(session_id)
        return InterruptResult(
            session_id=session_id,
            reason=reason,
            accepted=True,
            cancelled_tasks=1,
            already_interrupting=False,
        )

    def reset_session(self, session_id: str) -> None:
        """重置测试会话。"""
        if session_id not in self.sessions:
            raise SessionNotFoundError("session not found", session_id=session_id)
        self.reset_calls.append(session_id)
        self.messages[session_id] = []
        self.sessions[session_id]["message_count"] = 0

    async def get_status_snapshot(self, session_id: str):
        """返回测试状态。"""
        if session_id not in self.sessions:
            raise SessionNotFoundError("session not found", session_id=session_id)
        return RuntimeStatusSnapshot(
            version="0.1.5",
            model="mimo-v2.5",
            start_time=1.0,
            last_usage={"prompt_tokens": 1, "completion_tokens": 2},
            context_window_tokens=4096,
            session_msg_count=3,
            context_tokens_estimate=128,
            search_usage_text=None,
        )

    async def get_status_payload(self) -> dict:
        """返回 vNext 状态。"""
        return {
            "version": "0.1.5",
            "model": "mimo-v2.5",
            "start_time": 1.0,
            "last_usage": {"prompt_tokens": 1, "completion_tokens": 2},
            "context_window_tokens": 4096,
            "session_msg_count": 3,
            "context_tokens_estimate": 128,
            "search_usage_text": None,
        }

    async def get_bootstrap_snapshot(self) -> dict:
        """返回 bootstrap 快照。"""
        return {
            "status": await self.get_status_payload(),
            "sessions": list(self.sessions.values()),
            "provider_catalog": {
                "providers": [
                    {
                        "name": "deepseek",
                        "display_name": "DeepSeek",
                        "backend": "deepseek",
                        "default_api_base": "https://api.deepseek.com",
                        "api_base_editable": False,
                        "is_gateway": False,
                        "is_local": False,
                        "is_direct": False,
                        "strip_model_prefix": False,
                        "supports_prompt_caching": False,
                    }
                ]
            },
            "provider_state": self.provider_state,
            "tasks": self.list_task_items(),
            "sidebar": self.sidebar,
        }

    def list_sessions(
        self,
        *,
        page_token: str | None = None,
        page_size: int | None = None,
        include_archived: bool | None = None,
    ) -> dict:
        """列出测试会话。"""
        if page_token == "bad-token":
            raise InvalidPageTokenError("invalid page token")
        sessions = sorted(
            self.sessions.values(),
            key=lambda item: (-int(item["updated_at_ms"]), str(item["session_id"])),
        )
        if not include_archived:
            sessions = [item for item in sessions if not item.get("archived")]
        if page_size is not None and page_size > 0:
            sessions = sessions[:page_size]
        return {"sessions": sessions, "next_page_token": None, "total_count": len(self.sessions)}

    def create_session(self, session_id: str | None = None, *, title: str | None = None) -> dict:
        """创建测试会话。"""
        normalized = str(session_id or "").strip() or "remote:created"
        if normalized in self.sessions:
            raise DuplicateSessionIdError("duplicate session id", session_id=normalized)
        now_ms = int(datetime.now().timestamp() * 1000)
        payload = {
            "key": normalized,
            "session_id": normalized,
            "title": title,
            "created_at_ms": now_ms,
            "updated_at_ms": now_ms,
            "message_count": 0,
            "archived": False,
            "source": "remote",
        }
        self.sessions[normalized] = payload
        self.messages[normalized] = []
        return payload

    def get_session(self, session_id: str) -> dict:
        """读取测试会话。"""
        if session_id not in self.sessions:
            raise SessionNotFoundError("session not found", session_id=session_id)
        return self.sessions[session_id]

    def delete_session(self, session_id: str) -> dict:
        """删除测试会话。"""
        if session_id not in self.sessions:
            raise SessionNotFoundError("session not found", session_id=session_id)
        self.sessions.pop(session_id, None)
        self.messages.pop(session_id, None)
        return {"session_id": session_id, "deleted": True}

    def load_session_messages(
        self, session_id: str, *, limit: int = 100, cursor: int | None = None
    ) -> dict:
        """读取测试消息。"""
        del cursor
        if session_id not in self.sessions:
            raise SessionNotFoundError("session not found", session_id=session_id)
        messages = self.messages.get(session_id, [])[-limit:]
        return {
            "session_id": session_id,
            "messages": messages,
            "cursor": len(self.messages.get(session_id, [])),
            "next_cursor": None,
            "total_messages": len(self.messages.get(session_id, [])),
        }

    def get_sidebar_snapshot(self) -> dict:
        """返回侧栏快照。"""
        return self.sidebar

    def list_task_items(self) -> list[dict]:
        """列出任务。"""
        return list(self.tasks.values())

    def get_task_item(self, task_id: str) -> dict | None:
        """读取任务。"""
        return self.tasks.get(task_id)

    def create_task_from_schedule(
        self,
        *,
        instruction: str,
        schedule,
        source_session_key: str,
        target_channels: list[str] | None = None,
    ) -> dict:
        """创建任务。"""
        task_id = f"task_{len(self.tasks) + 1}"
        task = {
            "id": task_id,
            "title": instruction[:30],
            "instruction": instruction,
            "enabled": True,
            "schedule": {
                "kind": schedule.kind,
                "at_ms": schedule.at_ms,
                "every_ms": schedule.every_ms,
                "expr": schedule.expr,
                "tz": schedule.tz,
            },
            "next_run_at_ms": schedule.at_ms,
            "run_count": 0,
            "status": "pending",
            "target_channels": list(target_channels or []),
        }
        self.tasks[task_id] = task
        self.sidebar["tasks"] = [self._to_sidebar_task(task)]
        self.task_actions.append(
            (
                "create",
                {
                    "source_session_key": source_session_key,
                    "target_channels": target_channels or [],
                },
            )
        )
        return task

    @staticmethod
    def schedule_from_remote_payload(payload):
        """转换协议调度。"""
        from nomi.cron.types import CronSchedule

        return CronSchedule(
            kind=payload.kind,
            at_ms=payload.at_ms,
            every_ms=payload.every_ms,
            expr=payload.expr,
            tz=payload.tz,
        )

    def update_task_instruction(self, task_id: str, instruction: str) -> dict | None:
        """更新任务内容。"""
        task = self.tasks.get(task_id)
        if not task:
            return None
        task["instruction"] = instruction
        task["title"] = instruction[:30]
        return task

    def delete_task(self, task_id: str) -> bool:
        """删除任务。"""
        self.task_actions.append(("delete", {"task_id": task_id}))
        existed = self.tasks.pop(task_id, None) is not None
        self.sidebar["tasks"] = [self._to_sidebar_task(task) for task in self.tasks.values()]
        return existed

    def enable_task(self, task_id: str) -> dict | None:
        """启用任务。"""
        task = self.tasks.get(task_id)
        if task:
            task["enabled"] = True
        return task

    def disable_task(self, task_id: str) -> dict | None:
        """停用任务。"""
        task = self.tasks.get(task_id)
        if task:
            task["enabled"] = False
        return task

    @staticmethod
    def _to_sidebar_task(task: dict) -> dict:
        """转换为侧栏任务。"""
        schedule = task["schedule"]
        return {
            "id": task["id"],
            "title": task["title"],
            "instruction": task["instruction"],
            "enabled": task["enabled"],
            "scheduleKind": schedule["kind"],
            "scheduleAtMs": schedule.get("at_ms"),
            "scheduleEveryMs": schedule.get("every_ms"),
            "scheduleExpr": schedule.get("expr"),
            "scheduleTz": schedule.get("tz"),
            "nextRunAtMs": task.get("next_run_at_ms"),
            "runCount": task["run_count"],
            "status": task["status"],
            "targetChannels": task["target_channels"],
        }

    def list_skills(self) -> list[dict]:
        """列出 skills。"""
        return [
            {"name": item["name"], "key": item["name"], "path": item["path"], "description": ""}
            for item in self.sidebar["skills"]
        ]

    def install_skill(self, source: str) -> tuple[bool, str]:
        """安装 skill。"""
        self.skill_sources.append(source)
        self.sidebar["skills"] = [{"name": "demo-skill", "path": source}]
        return True, "已安装 skill：`demo-skill`。"

    def uninstall_skill(self, skill_name: str) -> tuple[bool, str]:
        """卸载 skill。"""
        self.uninstalled_skills.append(skill_name)
        self.sidebar["skills"] = []
        return True, f"已卸载 skill：`{skill_name}`。"

    def list_mcp_servers(self) -> list[dict]:
        """列出 MCP server。"""
        return self.sidebar["mcpServers"]

    async def create_mcp_server(self, mcp_name: str, payload: dict) -> dict:
        """创建 MCP server。"""
        self.mcp_actions.append(("create", mcp_name, payload))
        item = {"name": mcp_name, **payload}
        self.sidebar["mcpServers"] = [item]
        return item

    async def update_mcp_server(self, mcp_name: str, payload: dict) -> dict:
        """更新 MCP server。"""
        self.mcp_actions.append(("update", mcp_name, payload))
        item = {"name": mcp_name, **payload}
        self.sidebar["mcpServers"] = [item]
        return item

    async def delete_mcp_server(self, mcp_name: str) -> bool:
        """删除 MCP server。"""
        self.mcp_actions.append(("delete", mcp_name, None))
        self.sidebar["mcpServers"] = []
        return True

    async def enable_mcp_server(self, mcp_name: str) -> dict | None:
        """启用 MCP server。"""
        self.mcp_actions.append(("enable", mcp_name, None))
        return {"name": mcp_name, "enabled": True}

    async def disable_mcp_server(self, mcp_name: str) -> dict | None:
        """停用 MCP server。"""
        self.mcp_actions.append(("disable", mcp_name, None))
        return {"name": mcp_name, "enabled": False}

    async def clear_remote_runtime_state(self) -> None:
        """清理 remote 运行态。"""
        self.clear_calls += 1
        self.sidebar = {"tasks": [], "skills": [], "mcpServers": []}
        self.tasks = {}

    def get_provider_state_snapshot(self) -> dict:
        """返回 provider 状态。"""
        return self.provider_state

    def list_providers(self) -> dict:
        """返回 provider 列表。"""
        return self.provider_state

    def update_provider(
        self,
        provider_name: str,
        *,
        api_key=Ellipsis,
        token_plan_api_key=Ellipsis,
        api_base=Ellipsis,
        model=Ellipsis,
        clear_api_key=Ellipsis,
        clear_token_plan_api_key=Ellipsis,
    ) -> dict:
        """更新 provider。"""
        update = {
            "provider": provider_name,
            "api_key": api_key,
            "token_plan_api_key": token_plan_api_key,
            "api_base": api_base,
            "model": model,
            "clear_api_key": clear_api_key,
            "clear_token_plan_api_key": clear_token_plan_api_key,
        }
        self.provider_updates.append(update)
        settings = {
            "provider": provider_name,
            "display_name": "Custom" if provider_name == "custom" else "DeepSeek",
            "backend": "openai_compat" if provider_name == "custom" else "deepseek",
            "builtin": provider_name != "custom",
            "editable": True,
            "deletable": False,
            "api_key_set": False if clear_api_key is True else api_key not in (Ellipsis, None, ""),
            "api_key_preview": None
            if clear_api_key is True or api_key in (Ellipsis, None, "")
            else "…9999",
            "saved_model": None if model in (Ellipsis, None, "") else model,
            "api_base": None if api_base in (Ellipsis, None, "") else api_base,
            "api_base_editable": provider_name == "custom",
            "default_api_base": None if provider_name == "custom" else "https://api.deepseek.com",
            "source": "config",
        }
        return {"provider": provider_name, "settings": settings, "requires_runtime_reload": True}

    def set_active_provider(self, provider_name: str, *, model: str | None = None) -> dict:
        """切换 provider。"""
        self.active_provider_updates.append({"provider": provider_name, "model": model})
        active = {"provider": provider_name, "model": model or "fallback-model"}
        self.provider_state["active"] = active
        return {"active": active, "requires_runtime_reload": True}

    async def reload_runtime(self) -> dict:
        """重载 runtime。"""
        self.runtime_reload_calls += 1
        return {
            "active": dict(self.provider_state["active"]),
            "provider_state": self.provider_state,
        }

    async def receive_instance_relation_request(
        self,
        payload: dict,
        *,
        invite_id: str,
        invite_secret: str,
    ) -> dict:
        """记录 instance 关系请求。"""
        self.instance_calls.append(("request", payload, invite_id, invite_secret))
        return {"ok": True, "status": "pending", "key": payload.get("from_key")}

    async def receive_instance_relation_response(
        self,
        payload: dict,
        *,
        response_token: str | None = None,
        relation_id: str | None = None,
        relation_token: str | None = None,
    ) -> dict:
        """记录 instance 关系响应。"""
        self.instance_calls.append(
            ("response", payload, response_token, relation_id, relation_token)
        )
        return {"ok": True, "status": payload.get("status"), "key": payload.get("from_key")}

    async def receive_instance_message(
        self,
        payload: dict,
        *,
        relation_id: str,
        relation_token: str,
    ) -> dict:
        """记录 instance 消息。"""
        self.instance_calls.append(("message", payload, relation_id, relation_token))
        if payload.get("from_key") == "blocked":
            raise PermissionError("instance relation blocked does not allow chat")
        return {
            "ok": True,
            "session_id": f"instance:{payload.get('from_key')}",
            "content": "instance pong",
            "stop_reason": "completed",
        }


class _RelationRuntime:
    """测试用真实关系握手 runtime。"""

    def __init__(self, *, key: str, url: str) -> None:
        """初始化一份关系状态。"""
        from nomi.instance_channel.manager import InstanceRelationManager
        from nomi.instance_channel.store import (
            InstanceInviteStore,
            InstanceRelationRequestStore,
            InstanceRelationStore,
        )

        self.key = key
        self.url = url
        self.bus = MessageBus()
        self.agent_loop = SimpleNamespace(sessions=_FakeSessions())
        self._tmpdir = tempfile.TemporaryDirectory()
        self.instance_relations = InstanceRelationManager(
            invite_store=InstanceInviteStore(Path(self._tmpdir.name) / "instance-invite.json"),
            request_store=InstanceRelationRequestStore(
                Path(self._tmpdir.name) / "instance-requests.json"
            ),
            relation_store=InstanceRelationStore(
                Path(self._tmpdir.name) / "instance-relations.json"
            ),
        )

    def build_invite(self) -> tuple[str, str]:
        """生成测试用邀请码凭证。"""
        invite, secret = self.instance_relations.build_invite(key=self.key, url=self.url)
        return invite.invite_id, secret

    async def receive_instance_relation_request(
        self,
        payload: dict,
        *,
        invite_id: str,
        invite_secret: str,
    ) -> dict:
        """处理关系申请。"""
        invite = self.instance_relations.consume_invite(
            invite_id=invite_id,
            secret=invite_secret,
        )
        request = self.instance_relations.create_incoming_request(
            key=str(payload["from_key"]),
            url=str(payload["from_url"]),
            requested_permission=str(payload["requested_permission"]),
            response_token=str(payload["response_token"]),
            invite_id=invite.invite_id,
        )
        return {"ok": True, "status": "pending", "key": request.key}

    async def receive_instance_relation_response(
        self,
        payload: dict,
        *,
        response_token: str | None = None,
        relation_id: str | None = None,
        relation_token: str | None = None,
    ) -> dict:
        """处理关系确认。"""
        key = str(payload.get("from_key") or "").strip()
        if str(payload.get("status")) == "accepted":
            request = self.instance_relations.get_request(key)
            if request is None or request.response_token != response_token:
                raise PermissionError("invalid response token")
            relation = self.instance_relations.accept_outgoing(
                key=key,
                url=str(payload.get("from_url") or request.url),
                relation_id=str(payload["relation_id"]),
                relation_token=str(payload["relation_token"]),
            )
            return {"ok": True, "status": "accepted", "key": relation.key}
        if str(payload.get("status")) == "removed":
            relation = self.instance_relations.require_by_relation_token(
                relation_id=str(relation_id or ""),
                token=str(relation_token or ""),
            )
            self.instance_relations.apply_remote_remove(relation)
            return {"ok": True, "status": "removed", "key": relation.key}
        if str(payload.get("status")) == "withdrawn":
            request = self.instance_relations.get_request(key)
            if request is None or request.response_token != response_token:
                raise PermissionError("invalid response token")
            self.instance_relations.apply_remote_withdraw(key)
            return {"ok": True, "status": "withdrawn", "key": key}
        self.instance_relations.reject_outgoing(key)
        return {"ok": True, "status": "rejected", "key": key}


def _config(port: int) -> Config:
    """构造 remote 测试配置。"""
    config = Config()
    config.remote.enabled = True
    config.remote.host = "127.0.0.1"
    config.remote.port = port
    config.remote.auth_token = "secret-token"
    return config


def _auth() -> dict[str, str]:
    """返回测试鉴权头。"""
    return {"Authorization": "Bearer secret-token"}


async def _next_sse_event(lines: AsyncIterator[str], timeout: float | None = None) -> dict | None:
    """读取下一条 SSE 事件。"""
    async def _read() -> dict:
        event_type = None
        async for line in lines:
            if not line or line.startswith(":"):
                continue
            if line.startswith("event: "):
                event_type = line.removeprefix("event: ")
                continue
            if line.startswith("data: "):
                payload = json.loads(line.removeprefix("data: "))
                if event_type is not None:
                    assert payload["type"] == event_type
                return payload
        raise RuntimeError("SSE stream ended")

    if timeout is None:
        return await _read()
    try:
        return await asyncio.wait_for(_read(), timeout=timeout)
    except TimeoutError:
        return None
    raise AssertionError("SSE stream ended")


@pytest.mark.asyncio
async def test_remote_http_bootstrap_sessions_turns_and_sse() -> None:
    """HTTP 操作和 SSE turn 事件应形成闭环。"""
    runtime = _FakeRuntime()
    server = RemoteServer(_config(8876), runtime)  # type: ignore[arg-type]

    await server.start()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            preflight = await client.options("http://127.0.0.1:8876/v1/bootstrap")
            assert preflight.status_code == 204
            assert preflight.headers["access-control-allow-origin"] == "*"

            unauthorized = await client.get("http://127.0.0.1:8876/v1/bootstrap")
            assert unauthorized.status_code == 401
            assert unauthorized.headers["access-control-allow-origin"] == "*"

            bootstrap = await client.get("http://127.0.0.1:8876/v1/bootstrap", headers=_auth())
            assert bootstrap.status_code == 200
            assert bootstrap.headers["access-control-allow-origin"] == "*"
            assert bootstrap.json()["provider_state"]["active"]["provider"] == "deepseek"
            assert bootstrap.json()["sessions"][0]["session_id"] == "desktop:test"

            created = await client.post(
                "http://127.0.0.1:8876/v1/sessions",
                headers=_auth(),
                json={"session_id": "desktop:new", "title": "New"},
            )
            assert created.status_code == 201
            assert created.json()["session"]["session_id"] == "desktop:new"

            listed = await client.get("http://127.0.0.1:8876/v1/sessions", headers=_auth())
            assert listed.json()["page"]["total_count"] == 2

            messages = await client.get(
                "http://127.0.0.1:8876/v1/sessions/desktop:test/messages", headers=_auth()
            )
            assert messages.json()["messages"][0]["content"] == "hello"

            async with client.stream(
                "GET", "http://127.0.0.1:8876/v1/events?token=secret-token"
            ) as stream:
                lines = stream.aiter_lines()
                connected = await asyncio.wait_for(_next_sse_event(lines), timeout=2.0)
                assert connected["type"] == "runtime.connected"

                queued = await client.post(
                    "http://127.0.0.1:8876/v1/sessions/desktop:test/turns",
                    headers=_auth(),
                    json={
                        "content": "你好",
                        "client_id": "client-a",
                        "metadata": {"source": "test"},
                    },
                )
                assert queued.status_code == 202
                assert queued.json() == {
                    "turn_id": "turn_fake",
                    "session_id": "desktop:test",
                    "status": "queued",
                }
                assert runtime.sent_messages[-1] == (
                    "desktop:test",
                    "你好",
                    "client-a",
                    {"source": "test"},
                )

                started = await asyncio.wait_for(_next_sse_event(lines), timeout=2.0)
                assert started["type"] == "turn.started"
                assert started["data"]["session_id"] == "desktop:test"

                await runtime.bus.publish_outbound(
                    OutboundMessage(
                        channel="desktop",
                        chat_id="test",
                        content="片段",
                        metadata={
                            "_session_id": "desktop:test",
                            "_stream_delta": True,
                            "_turn_id": "turn_fake",
                        },
                    )
                )
                delta = await asyncio.wait_for(_next_sse_event(lines), timeout=2.0)
                assert delta["type"] == "turn.delta"
                assert delta["data"]["content"] == "片段"

                await runtime.bus.publish_outbound(
                    OutboundMessage(
                        channel="desktop",
                        chat_id="test",
                        content="最终回复",
                        metadata={"_session_id": "desktop:test", "_turn_id": "turn_fake"},
                    )
                )
                completed = await asyncio.wait_for(_next_sse_event(lines), timeout=2.0)
                assert completed["type"] == "turn.completed"
                assert completed["data"]["stop_reason"] == "completed"

                await runtime.bus.publish_outbound(
                    OutboundMessage(
                        channel="desktop",
                        chat_id="test",
                        content="失败",
                        metadata={
                            "_session_id": "desktop:test",
                            "_turn_id": "turn_failed",
                            "_failed": True,
                            "_stop_reason": "error",
                            "_error": "provider failed",
                        },
                    )
                )
                failed = await asyncio.wait_for(_next_sse_event(lines), timeout=2.0)
                assert failed["type"] == "turn.failed"
                assert failed["data"]["stop_reason"] == "error"
                assert failed["data"]["error"] == "provider failed"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_remote_legacy_ws_route_is_removed() -> None:
    """旧 /ws command 面不应继续暴露。"""
    runtime = _FakeRuntime()
    server = RemoteServer(_config(8877), runtime)  # type: ignore[arg-type]

    await server.start()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://127.0.0.1:8877/ws?token=secret-token")
            assert response.status_code == 404
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_remote_sse_unknown_last_event_id_emits_single_resync() -> None:
    """SSE 游标无法补齐时应只给当前连接发送一次 resync。"""
    runtime = _FakeRuntime()
    server = RemoteServer(_config(8879), runtime)  # type: ignore[arg-type]

    await server.start()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            async with client.stream(
                "GET",
                "http://127.0.0.1:8879/v1/events?token=secret-token",
                headers={"Last-Event-ID": "missing"},
            ) as stream:
                lines = stream.aiter_lines()
                resync = await asyncio.wait_for(_next_sse_event(lines), timeout=2.0)
                assert resync["type"] == "runtime.resync_required"

                connected = await asyncio.wait_for(_next_sse_event(lines), timeout=2.0)
                assert connected["type"] == "runtime.connected"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_remote_http_provider_tasks_resources_and_errors() -> None:
    """provider、task、skill、mcp 均应走 HTTP API。"""
    runtime = _FakeRuntime()
    server = RemoteServer(_config(8887), runtime)  # type: ignore[arg-type]

    await server.start()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            provider_state = await client.get(
                "http://127.0.0.1:8887/v1/providers/state", headers=_auth()
            )
            assert provider_state.json()["provider_state"]["active"]["provider"] == "deepseek"

            updated = await client.patch(
                "http://127.0.0.1:8887/v1/providers/custom",
                headers=_auth(),
                json={
                    "api_key": "sk-demo",
                    "api_base": "https://example.com/v1",
                    "model": "gpt-test",
                },
            )
            assert updated.status_code == 200
            assert updated.json()["settings"]["saved_model"] == "gpt-test"
            assert runtime.provider_updates[0]["provider"] == "custom"

            active = await client.put(
                "http://127.0.0.1:8887/v1/providers/active",
                headers=_auth(),
                json={"provider": "minimax", "model": "MiniMax-M2.7"},
            )
            assert active.json()["active"]["provider"] == "minimax"

            reloaded = await client.post("http://127.0.0.1:8887/v1/runtime/reload", headers=_auth())
            assert reloaded.json()["active"]["provider"] == "minimax"
            assert runtime.runtime_reload_calls == 1

            task = await client.post(
                "http://127.0.0.1:8887/v1/tasks",
                headers=_auth(),
                json={
                    "instruction": "提醒喝水",
                    "source_session_key": "desktop:test",
                    "schedule": {"kind": "every", "every_ms": 60000},
                    "target_channels": ["weixin"],
                },
            )
            assert task.status_code == 201
            task_id = task.json()["task"]["id"]
            assert task.json()["task"]["target_channels"] == ["weixin"]

            disabled = await client.post(
                f"http://127.0.0.1:8887/v1/tasks/{task_id}/disable", headers=_auth()
            )
            assert disabled.json()["task"]["enabled"] is False

            upload = await client.post(
                "http://127.0.0.1:8887/v1/skills/uploads",
                headers=_auth(),
                files={"file": ("demo.zip", b"fake zip content", "application/zip")},
            )
            assert upload.status_code == 200
            installed = await client.post(
                "http://127.0.0.1:8887/v1/skills",
                headers=_auth(),
                json={"upload_token": upload.json()["upload_token"]},
            )
            assert installed.json()["resource"] == "skill"
            assert runtime.skill_sources[0].endswith(".zip")

            mcp = await client.post(
                "http://127.0.0.1:8887/v1/mcp",
                headers=_auth(),
                json={
                    "name": "filesystem",
                    "mcp": {
                        "enabled": True,
                        "type": "stdio",
                        "command": "npx",
                        "args": ["-y"],
                        "enabled_tools": ["*"],
                        "env": {},
                        "headers": {},
                    },
                },
            )
            assert mcp.status_code == 201
            assert mcp.json()["mcp"]["name"] == "filesystem"
            assert mcp.json()["mcp"]["enabled_tools"] == ["*"]

            missing = await client.get(
                "http://127.0.0.1:8887/v1/sessions/desktop:missing", headers=_auth()
            )
            assert missing.status_code == 404
            assert missing.json()["error"]["code"] == "session_not_found"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_remote_http_validation_error_includes_fields() -> None:
    """provider 字段级错误应出现在统一 HTTP error details 中。"""
    runtime = _FakeRuntime()

    def _raise_validation_error(*_args, **_kwargs):
        raise ProviderApiBaseNotEditableError(
            "api_base is not editable for provider deepseek",
            fields=[
                {
                    "field": "api_base",
                    "code": "not_editable",
                    "message": "api_base is read-only for this provider",
                }
            ],
        )

    runtime.update_provider = _raise_validation_error  # type: ignore[method-assign]
    server = RemoteServer(_config(8888), runtime)  # type: ignore[arg-type]

    await server.start()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.patch(
                "http://127.0.0.1:8888/v1/providers/deepseek",
                headers=_auth(),
                json={"api_base": "https://example.com/v1"},
            )
            assert response.status_code == 400
            assert response.json()["error"]["code"] == "provider_api_base_not_editable"
            assert response.json()["error"]["details"]["fields"][0]["field"] == "api_base"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_remote_instance_channel_routes_require_auth_and_delegate() -> None:
    """instance 内部通道路由应鉴权并委托 runtime。"""
    runtime = _FakeRuntime()
    server = RemoteServer(_config(8892), runtime)  # type: ignore[arg-type]

    await server.start()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            unauthorized = await client.post(
                "http://127.0.0.1:8892/v1/instance/relations/request",
                json={"from_key": "xmy"},
            )
            assert unauthorized.status_code == 401

            request = await client.post(
                "http://127.0.0.1:8892/v1/instance/relations/request",
                headers={
                    "X-Nomi-Invite-Id": "inv-1",
                    "Authorization": "Bearer invite-secret",
                },
                json={
                    "from_key": "xmy",
                    "from_url": "http://127.0.0.1:8766",
                    "requested_permission": "chat",
                    "response_token": "response-token",
                },
            )
            assert request.status_code == 200
            assert request.json()["status"] == "pending"

            response = await client.post(
                "http://127.0.0.1:8892/v1/instance/relations/response",
                headers={"Authorization": "Bearer response-token"},
                json={"from_key": "xmy", "status": "accepted"},
            )
            assert response.status_code == 200

            message = await client.post(
                "http://127.0.0.1:8892/v1/instance/messages",
                headers={
                    "X-Nomi-Relation-Id": "rel-1",
                    "Authorization": "Bearer relation-token",
                },
                json={"from_key": "xmy", "content": "ping"},
            )
            assert message.status_code == 200
            assert message.json()["content"] == "instance pong"

            forbidden = await client.post(
                "http://127.0.0.1:8892/v1/instance/messages",
                headers={
                    "X-Nomi-Relation-Id": "rel-1",
                    "Authorization": "Bearer relation-token",
                },
                json={"from_key": "blocked", "content": "ping"},
            )
            assert forbidden.status_code == 403
            assert forbidden.json()["error"]["code"] == "forbidden"

        assert runtime.instance_calls == [
            (
                "request",
                {
                    "from_key": "xmy",
                    "from_url": "http://127.0.0.1:8766",
                    "requested_permission": "chat",
                    "response_token": "response-token",
                },
                "inv-1",
                "invite-secret",
            ),
            ("response", {"from_key": "xmy", "status": "accepted"}, "response-token", None, None),
            ("message", {"from_key": "xmy", "content": "ping"}, "rel-1", "relation-token"),
            ("message", {"from_key": "blocked", "content": "ping"}, "rel-1", "relation-token"),
        ]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_remote_instance_relation_http_accept_round_trip() -> None:
    """两个 instance 通过内部 HTTP 路由应能完成申请与确认闭环。"""
    runtime_a = _RelationRuntime(
        key="a",
        url="http://127.0.0.1:8893",
    )
    runtime_b = _RelationRuntime(
        key="b",
        url="http://127.0.0.1:8894",
    )
    config_a = _config(8893)
    config_b = _config(8894)
    config_a.remote.auth_token = "token-a"
    config_b.remote.auth_token = "token-b"
    server_a = RemoteServer(config_a, runtime_a)  # type: ignore[arg-type]
    server_b = RemoteServer(config_b, runtime_b)  # type: ignore[arg-type]

    await server_a.start()
    await server_b.start()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            invite_id, invite_secret = runtime_b.build_invite()
            response_token = "response-token-a"
            runtime_a.instance_relations.create_outgoing_request(
                key="b",
                url="http://127.0.0.1:8894",
                requested_permission="chat",
                response_token=response_token,
                invite_id=invite_id,
            )
            request = await client.post(
                "http://127.0.0.1:8894/v1/instance/relations/request",
                headers={
                    "X-Nomi-Invite-Id": invite_id,
                    "Authorization": f"Bearer {invite_secret}",
                },
                json={
                    "from_key": "a",
                    "from_url": "http://127.0.0.1:8893",
                    "requested_permission": "chat",
                    "response_token": response_token,
                },
            )
            assert request.status_code == 200

            request_b = runtime_b.instance_relations.get_request("a")
            assert request_b is not None
            _, relation_b = runtime_b.instance_relations.accept_incoming("a", "chat")

            accept = await client.post(
                "http://127.0.0.1:8893/v1/instance/relations/response",
                headers={"Authorization": f"Bearer {response_token}"},
                json={
                    "from_key": "b",
                    "from_url": "http://127.0.0.1:8894",
                    "status": "accepted",
                    "relation_id": relation_b.relation_id,
                    "relation_token": relation_b.relation_token,
                },
            )
            assert accept.status_code == 200

            relation_a = runtime_a.instance_relations.get_relation("b")
            assert relation_a is not None
            assert relation_a.relation_id == relation_b.relation_id
            assert relation_a.permission == "chat"
    finally:
        await server_a.stop()
        await server_b.stop()


@pytest.mark.asyncio
async def test_remote_instance_relation_http_withdraw_round_trip() -> None:
    """申请方撤回时，双方 pending request 都应被删除。"""
    runtime_a = _RelationRuntime(
        key="a",
        url="http://127.0.0.1:8895",
    )
    runtime_b = _RelationRuntime(
        key="b",
        url="http://127.0.0.1:8896",
    )
    config_a = _config(8895)
    config_b = _config(8896)
    config_a.remote.auth_token = "token-a"
    config_b.remote.auth_token = "token-b"
    server_a = RemoteServer(config_a, runtime_a)  # type: ignore[arg-type]
    server_b = RemoteServer(config_b, runtime_b)  # type: ignore[arg-type]

    await server_a.start()
    await server_b.start()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            invite_id, invite_secret = runtime_b.build_invite()
            response_token = "response-token-a"
            runtime_a.instance_relations.create_outgoing_request(
                key="b",
                url="http://127.0.0.1:8896",
                requested_permission="chat",
                response_token=response_token,
                invite_id=invite_id,
            )
            request = await client.post(
                "http://127.0.0.1:8896/v1/instance/relations/request",
                headers={
                    "X-Nomi-Invite-Id": invite_id,
                    "Authorization": f"Bearer {invite_secret}",
                },
                json={
                    "from_key": "a",
                    "from_url": "http://127.0.0.1:8895",
                    "requested_permission": "chat",
                    "response_token": response_token,
                },
            )
            assert request.status_code == 200
            runtime_a.instance_relations.withdraw_outgoing("b")

            withdraw = await client.post(
                "http://127.0.0.1:8896/v1/instance/relations/response",
                headers={"Authorization": f"Bearer {response_token}"},
                json={"from_key": "a", "status": "withdrawn"},
            )

            assert withdraw.status_code == 200
            assert runtime_a.instance_relations.get_request("b") is None
            assert runtime_b.instance_relations.get_request("a") is None
    finally:
        await server_a.stop()
        await server_b.stop()


@pytest.mark.asyncio
async def test_remote_instance_user_request_routes_are_removed() -> None:
    """开放式用户请求内部路由已移除。"""
    runtime = _FakeRuntime()
    server = RemoteServer(_config(8897), runtime)  # type: ignore[arg-type]

    await server.start()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            unauthorized = await client.post(
                "http://127.0.0.1:8897/v1/instance/user-requests",
                headers=_auth(),
                json={"prompt": "今晚有安排吗？"},
            )
            assert unauthorized.status_code == 404

            created = await client.post(
                "http://127.0.0.1:8897/v1/instance/user-requests",
                headers={
                    "X-Nomi-Relation-Id": "rel-1",
                    "Authorization": "Bearer relation-token",
                },
                json={"request_id": "req-1", "prompt": "今晚有安排吗？"},
            )
            assert created.status_code == 404

            answered = await client.post(
                "http://127.0.0.1:8897/v1/instance/user-requests/req-1/response",
                headers={
                    "X-Nomi-Relation-Id": "rel-1",
                    "Authorization": "Bearer relation-token",
                },
                json={"answer": "可以"},
            )
            assert answered.status_code == 404

            cancelled = await client.post(
                "http://127.0.0.1:8897/v1/instance/user-requests/req-2/cancel",
                headers={
                    "X-Nomi-Relation-Id": "rel-1",
                    "Authorization": "Bearer relation-token",
                },
                json={"status": "cancelled"},
            )
            assert cancelled.status_code == 404
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_remote_sse_session_save_and_global_task_delivery_events() -> None:
    """SSE 应广播跨 channel session 保存和全局任务投递。"""
    runtime = _FakeRuntime()
    server = RemoteServer(_config(8882), runtime)  # type: ignore[arg-type]

    await server.start()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            async with client.stream(
                "GET", "http://127.0.0.1:8882/v1/events?token=secret-token"
            ) as stream:
                lines = stream.aiter_lines()
                connected = await asyncio.wait_for(_next_sse_event(lines), timeout=2.0)
                assert connected["type"] == "runtime.connected"

                session = SimpleNamespace(
                    key="weixin:wx-user",
                    messages=[
                        {"role": "user", "content": "微信消息", "timestamp": "2026-05-13T12:00:00"}
                    ],
                )
                runtime.sessions["weixin:wx-user"] = {
                    "key": "weixin:wx-user",
                    "session_id": "weixin:wx-user",
                    "title": None,
                    "created_at_ms": 1,
                    "updated_at_ms": 2,
                    "message_count": 1,
                    "archived": False,
                    "source": "weixin",
                }
                runtime.agent_loop.sessions.emit_saved(session, session.messages)
                appended = await asyncio.wait_for(_next_sse_event(lines), timeout=2.0)
                assert appended["type"] == "session.message_appended"
                assert appended["data"]["session_id"] == "weixin:wx-user"
                updated = await asyncio.wait_for(_next_sse_event(lines), timeout=2.0)
                assert updated["type"] == "session.updated"

                await runtime.bus.publish_outbound(
                    OutboundMessage(
                        channel="weixin",
                        chat_id="wx-user",
                        content="全局提醒",
                        metadata={
                            "_task_delivery_id": "task_1",
                            "_global_reminder_broadcast": True,
                            "_session_id": "desktop:test",
                        },
                    )
                )

                await runtime.bus.publish_outbound(
                    OutboundMessage(
                        channel="remote",
                        chat_id="desktop:test",
                        content="定向任务提醒",
                        metadata={
                            "_task_delivery_id": "task_2",
                            "_session_id": "desktop:test",
                        },
                    )
                )
                delivered = await asyncio.wait_for(_next_sse_event(lines), timeout=2.0)
                assert delivered["type"] == "task.delivered"
                assert delivered["data"]["content"] == "定向任务提醒"
    finally:
        await server.stop()
