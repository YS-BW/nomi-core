"""remote desktop shell 服务测试。"""

from __future__ import annotations

import json

import pytest
from websockets.asyncio.client import connect

from nomi.bus.events import OutboundMessage
from nomi.bus.queue import MessageBus
from nomi.config.schema import Config
from nomi.remote.server import RemoteServer
from nomi.runtime.models import InterruptResult, RuntimeStatusSnapshot


class _FakeRuntime:
    def __init__(self) -> None:
        self.bus = MessageBus()
        self.sent_messages: list[tuple[str, str, str, dict | None]] = []
        self.interrupt_calls: list[str] = []
        self.sidebar = {
            "tasks": [],
            "skills": [],
            "mcpServers": [],
        }
        self.task_actions: list[tuple[str, dict]] = []
        self.skill_sources: list[str] = []
        self.uninstalled_skills: list[str] = []
        self.mcp_actions: list[tuple[str, str, dict | None]] = []
        self.clear_calls = 0

    async def send_user_message(
        self,
        session_id: str,
        content: str,
        *,
        client_id: str,
        metadata: dict | None = None,
    ) -> None:
        self.sent_messages.append((session_id, content, client_id, metadata))

    def interrupt_session(self, session_id: str, reason: str = "user_interrupt"):
        self.interrupt_calls.append(session_id)
        return InterruptResult(
            session_id=session_id,
            reason=reason,
            accepted=True,
            cancelled_tasks=1,
            already_interrupting=False,
        )

    async def get_status_snapshot(self, session_id: str):
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

    def list_sessions(self) -> list[dict]:
        return [{"key": "desktop:test", "updated_at": "2026-05-06T12:00:00"}]

    def load_session_messages(self, session_id: str, *, limit: int = 100, cursor: int | None = None) -> dict:
        return {
            "session_id": session_id,
            "messages": [{"role": "user", "content": "hello"}],
            "cursor": 1,
            "next_cursor": None,
            "total_messages": 1,
        }

    def get_sidebar_snapshot(self) -> dict:
        return self.sidebar

    def create_task_after(self, session_id: str, *, instruction: str, after_seconds: int) -> dict:
        self.task_actions.append(("create_after", {"session_id": session_id, "instruction": instruction, "after_seconds": after_seconds}))
        task = {"id": "task_after", "title": instruction}
        self.sidebar["tasks"] = [task]
        return task

    def create_task_at(self, session_id: str, *, instruction: str, at: str) -> dict:
        self.task_actions.append(("create_at", {"session_id": session_id, "instruction": instruction, "at": at}))
        task = {"id": "task_at", "title": instruction}
        self.sidebar["tasks"] = [task]
        return task

    def create_task_daily(self, session_id: str, *, instruction: str, daily_time: str) -> dict:
        self.task_actions.append(("create_daily", {"session_id": session_id, "instruction": instruction, "daily_time": daily_time}))
        task = {"id": "task_daily", "title": instruction}
        self.sidebar["tasks"] = [task]
        return task

    def create_task_every(self, session_id: str, *, instruction: str, every_seconds: int) -> dict:
        self.task_actions.append(("create_every", {"session_id": session_id, "instruction": instruction, "every_seconds": every_seconds}))
        task = {"id": "task_every", "title": instruction}
        self.sidebar["tasks"] = [task]
        return task

    def delete_task(self, task_id: str) -> bool:
        self.task_actions.append(("delete", {"task_id": task_id}))
        self.sidebar["tasks"] = []
        return True

    def enable_task(self, task_id: str) -> dict | None:
        self.task_actions.append(("enable", {"task_id": task_id}))
        return {"id": task_id}

    def disable_task(self, task_id: str) -> dict | None:
        self.task_actions.append(("disable", {"task_id": task_id}))
        return {"id": task_id}

    def update_task_instruction(self, task_id: str, instruction: str) -> dict | None:
        self.task_actions.append(("update_instruction", {"task_id": task_id, "instruction": instruction}))
        return {"id": task_id}

    def reschedule_task_after(self, task_id: str, *, after_seconds: int) -> dict | None:
        self.task_actions.append(("reschedule_after", {"task_id": task_id, "after_seconds": after_seconds}))
        return {"id": task_id}

    def reschedule_task_at(self, task_id: str, *, at: str) -> dict | None:
        self.task_actions.append(("reschedule_at", {"task_id": task_id, "at": at}))
        return {"id": task_id}

    def reschedule_task_daily(self, task_id: str, *, daily_time: str) -> dict | None:
        self.task_actions.append(("reschedule_daily", {"task_id": task_id, "daily_time": daily_time}))
        return {"id": task_id}

    def reschedule_task_every(self, task_id: str, *, every_seconds: int) -> dict | None:
        self.task_actions.append(("reschedule_every", {"task_id": task_id, "every_seconds": every_seconds}))
        return {"id": task_id}

    def install_skill(self, source: str) -> tuple[bool, str]:
        self.skill_sources.append(source)
        self.sidebar["skills"] = [{"name": "demo-skill", "path": source}]
        return True, "已安装 skill：`demo-skill`。"

    def uninstall_skill(self, skill_name: str) -> tuple[bool, str]:
        self.uninstalled_skills.append(skill_name)
        self.sidebar["skills"] = []
        return True, f"已卸载 skill：`{skill_name}`。"

    async def create_mcp_server(self, mcp_name: str, payload: dict) -> dict:
        self.mcp_actions.append(("create", mcp_name, payload))
        self.sidebar["mcpServers"] = [{"name": mcp_name, **payload}]
        return {"name": mcp_name}

    async def update_mcp_server(self, mcp_name: str, payload: dict) -> dict:
        self.mcp_actions.append(("update", mcp_name, payload))
        self.sidebar["mcpServers"] = [{"name": mcp_name, **payload}]
        return {"name": mcp_name}

    async def delete_mcp_server(self, mcp_name: str) -> bool:
        self.mcp_actions.append(("delete", mcp_name, None))
        self.sidebar["mcpServers"] = []
        return True

    async def enable_mcp_server(self, mcp_name: str) -> dict | None:
        self.mcp_actions.append(("enable", mcp_name, None))
        return {"name": mcp_name}

    async def disable_mcp_server(self, mcp_name: str) -> dict | None:
        self.mcp_actions.append(("disable", mcp_name, None))
        return {"name": mcp_name}

    async def clear_remote_runtime_state(self) -> None:
        self.clear_calls += 1
        self.sidebar = {"tasks": [], "skills": [], "mcpServers": []}


@pytest.mark.asyncio
async def test_remote_server_websocket_protocol() -> None:
    config = Config()
    config.remote.enabled = True
    config.remote.host = "127.0.0.1"
    config.remote.port = 8876
    config.remote.auth_token = "secret-token"
    runtime = _FakeRuntime()
    server = RemoteServer(config, runtime)  # type: ignore[arg-type]

    await server.start()
    try:
        async with connect(
            "ws://127.0.0.1:8876/ws",
            additional_headers={"Authorization": "Bearer secret-token"},
        ) as websocket:
            ready = json.loads(await websocket.recv())
            assert ready["type"] == "ready"

            await websocket.send(json.dumps({"type": "bind_session", "session_id": "desktop:test"}))
            bound = json.loads(await websocket.recv())
            assert bound == {"type": "session_bound", "session_id": "desktop:test"}

            await websocket.send(
                json.dumps(
                    {
                        "type": "send_message",
                        "session_id": "desktop:test",
                        "content": "你好",
                        "client_id": "client-a",
                    }
                )
            )
            started = json.loads(await websocket.recv())
            assert started == {"type": "turn_started", "session_id": "desktop:test"}
            assert runtime.sent_messages == [("desktop:test", "你好", "client-a", {})]

            await runtime.bus.publish_outbound(
                OutboundMessage(
                    channel="desktop",
                    chat_id="test",
                    content="片段",
                    metadata={"_session_id": "desktop:test", "_stream_delta": True},
                )
            )
            delta = json.loads(await websocket.recv())
            assert delta == {"type": "delta", "session_id": "desktop:test", "content": "片段"}

            await runtime.bus.publish_outbound(
                OutboundMessage(
                    channel="desktop",
                    chat_id="test",
                    content="",
                    metadata={"_session_id": "desktop:test", "_stream_end": True, "_resuming": False},
                )
            )
            stream_end = json.loads(await websocket.recv())
            assert stream_end == {
                "type": "stream_end",
                "session_id": "desktop:test",
                "resuming": False,
            }

            await runtime.bus.publish_outbound(
                OutboundMessage(
                    channel="desktop",
                    chat_id="test",
                    content="最终回复",
                    metadata={"_session_id": "desktop:test"},
                )
            )
            message = json.loads(await websocket.recv())
            completed = json.loads(await websocket.recv())
            assert message["type"] == "message"
            assert message["content"] == "最终回复"
            assert completed == {
                "type": "turn_completed",
                "session_id": "desktop:test",
                "stop_reason": "completed",
            }

            await websocket.send(json.dumps({"type": "list_sessions"}))
            session_list = json.loads(await websocket.recv())
            assert session_list["type"] == "session_list"
            assert session_list["sessions"][0]["key"] == "desktop:test"

            await websocket.send(
                json.dumps({"type": "load_history", "session_id": "desktop:test", "limit": 10})
            )
            history = json.loads(await websocket.recv())
            assert history["type"] == "history_snapshot"
            assert history["messages"][0]["content"] == "hello"

            await websocket.send(json.dumps({"type": "get_status", "session_id": "desktop:test"}))
            status = json.loads(await websocket.recv())
            assert status["type"] == "status_result"
            assert status["snapshot"]["model"] == "mimo-v2.5"

            await websocket.send(json.dumps({"type": "interrupt_turn", "session_id": "desktop:test"}))
            interrupt = json.loads(await websocket.recv())
            assert interrupt["type"] == "interrupt_result"
            assert runtime.interrupt_calls == ["desktop:test"]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_remote_server_allows_query_token_for_browser_demo() -> None:
    config = Config()
    config.remote.enabled = True
    config.remote.host = "127.0.0.1"
    config.remote.port = 8878
    config.remote.auth_token = "secret-token"
    runtime = _FakeRuntime()
    server = RemoteServer(config, runtime)  # type: ignore[arg-type]

    await server.start()
    try:
        async with connect("ws://127.0.0.1:8878/ws?token=secret-token") as websocket:
            ready = json.loads(await websocket.recv())
            assert ready["type"] == "ready"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_remote_server_rebinds_to_single_current_session() -> None:
    config = Config()
    config.remote.enabled = True
    config.remote.host = "127.0.0.1"
    config.remote.port = 8879
    config.remote.auth_token = "secret-token"
    runtime = _FakeRuntime()
    server = RemoteServer(config, runtime)  # type: ignore[arg-type]

    await server.start()
    try:
        async with connect(
            "ws://127.0.0.1:8879/ws",
            additional_headers={"Authorization": "Bearer secret-token"},
        ) as websocket:
            ready = json.loads(await websocket.recv())
            assert ready["type"] == "ready"

            await websocket.send(json.dumps({"type": "bind_session", "session_id": "desktop:one"}))
            bound_one = json.loads(await websocket.recv())
            assert bound_one == {"type": "session_bound", "session_id": "desktop:one"}

            await websocket.send(json.dumps({"type": "bind_session", "session_id": "desktop:two"}))
            bound_two = json.loads(await websocket.recv())
            assert bound_two == {"type": "session_bound", "session_id": "desktop:two"}

            await runtime.bus.publish_outbound(
                OutboundMessage(
                    channel="desktop",
                    chat_id="one",
                    content="旧会话消息",
                    metadata={"_session_id": "desktop:one"},
                )
            )
            await runtime.bus.publish_outbound(
                OutboundMessage(
                    channel="desktop",
                    chat_id="two",
                    content="当前会话消息",
                    metadata={"_session_id": "desktop:two"},
                )
            )

            current = json.loads(await websocket.recv())
            assert current["type"] == "message"
            assert current["session_id"] == "desktop:two"
            assert current["content"] == "当前会话消息"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_remote_server_health_endpoint() -> None:
    import httpx

    config = Config()
    config.remote.enabled = True
    config.remote.host = "127.0.0.1"
    config.remote.port = 8877
    config.remote.auth_token = "secret-token"
    runtime = _FakeRuntime()
    server = RemoteServer(config, runtime)  # type: ignore[arg-type]

    await server.start()
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("http://127.0.0.1:8877/health")
        assert response.status_code == 200
        assert response.json() == {"ok": True}
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_remote_server_sidebar_and_resource_commands() -> None:
    config = Config()
    config.remote.enabled = True
    config.remote.host = "127.0.0.1"
    config.remote.port = 8880
    config.remote.auth_token = "secret-token"
    runtime = _FakeRuntime()
    server = RemoteServer(config, runtime)  # type: ignore[arg-type]

    await server.start()
    try:
        async with connect(
            "ws://127.0.0.1:8880/ws",
            additional_headers={"Authorization": "Bearer secret-token"},
        ) as websocket:
            ready = json.loads(await websocket.recv())
            assert ready["type"] == "ready"

            await websocket.send(json.dumps({"type": "bind_session", "session_id": "desktop:test"}))
            bound = json.loads(await websocket.recv())
            assert bound["type"] == "session_bound"

            await websocket.send(json.dumps({"type": "get_sidebar", "session_id": "desktop:test"}))
            sidebar = json.loads(await websocket.recv())
            assert sidebar == {
                "type": "sidebar_snapshot",
                "session_id": "desktop:test",
                "sidebar": {"tasks": [], "skills": [], "mcpServers": []},
            }

            await websocket.send(
                json.dumps(
                    {
                        "type": "task_create_every",
                        "session_id": "desktop:test",
                        "instruction": "提醒喝水",
                        "every_seconds": 60,
                    }
                )
            )
            action = json.loads(await websocket.recv())
            snapshot = json.loads(await websocket.recv())
            assert action["type"] == "resource_action_result"
            assert action["resource"] == "task"
            assert action["action"] == "create_every"
            assert snapshot["type"] == "sidebar_snapshot"
            assert snapshot["sidebar"]["tasks"][0]["id"] == "task_every"

            await websocket.send(
                json.dumps(
                    {
                        "type": "mcp_create",
                        "session_id": "desktop:test",
                        "mcp_name": "filesystem",
                        "mcp": {
                            "enabled": True,
                            "type": "stdio",
                            "command": "npx",
                            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
                            "url": "",
                            "enabled_tools": ["*"],
                            "env": {},
                            "headers": {},
                        },
                    }
                )
            )
            action = json.loads(await websocket.recv())
            snapshot = json.loads(await websocket.recv())
            assert action["resource"] == "mcp"
            assert action["action"] == "create"
            assert snapshot["sidebar"]["mcpServers"][0]["name"] == "filesystem"

            await websocket.send(
                json.dumps(
                    {
                        "type": "clear_remote_runtime",
                        "session_id": "desktop:test",
                    }
                )
            )
            action = json.loads(await websocket.recv())
            snapshot = json.loads(await websocket.recv())
            assert action["action"] == "clear_remote_runtime"
            assert runtime.clear_calls == 1
            assert snapshot["sidebar"] == {"tasks": [], "skills": [], "mcpServers": []}
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_remote_server_skill_upload_and_install() -> None:
    import httpx

    config = Config()
    config.remote.enabled = True
    config.remote.host = "127.0.0.1"
    config.remote.port = 8881
    config.remote.auth_token = "secret-token"
    runtime = _FakeRuntime()
    server = RemoteServer(config, runtime)  # type: ignore[arg-type]

    await server.start()
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://127.0.0.1:8881/skills/upload",
                headers={"Authorization": "Bearer secret-token"},
                files={"file": ("demo-skill.zip", b"fake zip content", "application/zip")},
            )
            assert response.status_code == 200
            upload_token = response.json()["upload_token"]

        async with connect(
            "ws://127.0.0.1:8881/ws",
            additional_headers={"Authorization": "Bearer secret-token"},
        ) as websocket:
            await websocket.recv()
            await websocket.send(json.dumps({"type": "bind_session", "session_id": "desktop:test"}))
            await websocket.recv()
            await websocket.send(
                json.dumps(
                    {
                        "type": "skill_install",
                        "session_id": "desktop:test",
                        "upload_token": upload_token,
                    }
                )
            )
            action = json.loads(await websocket.recv())
            snapshot = json.loads(await websocket.recv())
            assert action["type"] == "resource_action_result"
            assert action["resource"] == "skill"
            assert action["action"] == "install"
            assert runtime.skill_sources[0].endswith(".zip")
            assert snapshot["sidebar"]["skills"][0]["name"] == "demo-skill"
    finally:
        await server.stop()
