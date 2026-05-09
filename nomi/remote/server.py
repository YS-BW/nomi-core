"""远程 desktop shell 服务端。"""

from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from pathlib import Path
from urllib.parse import parse_qs

from aiohttp import web
from loguru import logger

from nomi.config.schema import Config
from nomi.providers.factory.registry import build_provider_catalog
from nomi.remote.bridge import RemoteBridge
from nomi.remote.hub import RemoteClient, RemoteHub
from nomi.remote.schemas import RemoteCommand
from nomi.runtime import NomiRuntime
from nomi.runtime.protocol import (
    build_error_event,
    build_history_snapshot_event,
    build_interrupt_result_event,
    build_ready_event,
    build_resource_action_result_event,
    build_session_bound_event,
    build_session_created_event,
    build_session_deleted_event,
    build_session_list_event,
    build_sidebar_snapshot_event,
    build_status_result_event,
    build_turn_started_event,
)
from nomi.session.errors import (
    DuplicateSessionIdError,
    InvalidPageTokenError,
    SessionDeleteForbiddenError,
    SessionNotFoundError,
)


class RemoteServer:
    """承载远程 shell 协议的 HTTP + WebSocket 服务。"""

    def __init__(self, config: Config, runtime: NomiRuntime) -> None:
        """绑定配置和 runtime。"""
        self._config = config
        self._runtime = runtime
        self._hub = RemoteHub()
        self._bridge = RemoteBridge(self._hub)
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._unsubscribe_bus = None
        self._upload_tempdir = tempfile.TemporaryDirectory(prefix="nomi-remote-skills-")
        self._uploaded_archives: dict[str, Path] = {}

    async def start(self) -> None:
        """启动 HTTP + WebSocket 服务并注册 bus 旁路订阅。"""
        self._ensure_enabled()
        self._unsubscribe_bus = self._runtime.bus.subscribe_outbound(self._bridge.handle_outbound)
        self._app = web.Application()
        self._app.router.add_get("/health", self._handle_health)
        self._app.router.add_get("/ws", self._handle_ws)
        self._app.router.add_post("/skills/upload", self._handle_skill_upload)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._config.remote.host, self._config.remote.port)
        await self._site.start()
        logger.info(
            "Remote service started at ws://{}:{}",
            self._config.remote.host,
            self._config.remote.port,
        )

    async def wait(self) -> None:
        """等待服务结束。"""
        while self._runner is not None:
            await asyncio.sleep(3600)

    async def stop(self) -> None:
        """停止服务并释放订阅。"""
        if self._unsubscribe_bus is not None:
            self._unsubscribe_bus()
            self._unsubscribe_bus = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            self._app = None
        for path in self._uploaded_archives.values():
            path.unlink(missing_ok=True)
        self._uploaded_archives = {}
        self._upload_tempdir.cleanup()

    def _ensure_enabled(self) -> None:
        """校验当前 remote 配置可用。"""
        if not self._config.remote.enabled:
            raise ValueError("remote.enabled 未开启。")
        if not str(self._config.remote.auth_token or "").strip():
            raise ValueError("remote.auth_token 不能为空。")

    async def _handle_health(self, _request: web.Request) -> web.Response:
        """返回最小健康检查结果。"""
        return web.json_response({"ok": True})

    async def _handle_ws(self, request: web.Request) -> web.StreamResponse:
        """处理一条 WebSocket 连接。"""
        if not self._is_authorized(request, allow_query_token=True):
            return web.json_response({"error": "unauthorized"}, status=401)

        websocket = web.WebSocketResponse(heartbeat=20.0)
        await websocket.prepare(request)
        client_key = f"remote-{id(websocket)}"
        client = await self._hub.register(
            client_key,
            client_id=client_key,
            send_json=websocket.send_json,
        )
        try:
            await client.send_json(
                build_ready_event(
                    host=self._config.remote.host,
                    port=self._config.remote.port,
                    provider_catalog=build_provider_catalog(),
                )
            )
            async for message in websocket:
                if message.type == web.WSMsgType.TEXT:
                    await self._handle_command(client, raw=message.data)
                elif message.type == web.WSMsgType.ERROR:
                    break
        finally:
            await self._hub.unregister(client_key)
        return websocket

    async def _handle_skill_upload(self, request: web.Request) -> web.Response:
        """接收一个 zip skill 包，返回可供后续安装的 upload token。"""
        if not self._is_authorized(request, allow_query_token=False):
            return web.json_response({"error": "unauthorized"}, status=401)

        filename = str(request.headers.get("X-Skill-Filename", "") or "").strip()
        body = b""
        content_type = str(request.headers.get("Content-Type", "") or "")
        if content_type.startswith("multipart/form-data"):
            reader = await request.multipart()
            field = await reader.next()
            if field is None or field.name != "file":
                return web.json_response({"error": "file field is required"}, status=400)
            filename = filename or str(field.filename or "").strip()
            body = await field.read(decode=False)
        else:
            body = await request.read()

        if not filename.lower().endswith(".zip"):
            return web.json_response({"error": "only .zip skill packages are supported"}, status=400)
        if not body:
            return web.json_response({"error": "empty upload"}, status=400)

        upload_token = f"upload_{uuid.uuid4().hex[:16]}"
        target = Path(self._upload_tempdir.name) / f"{upload_token}.zip"
        target.write_bytes(body)
        self._uploaded_archives[upload_token] = target
        return web.json_response(
            {
                "ok": True,
                "upload_token": upload_token,
                "filename": filename,
            }
        )

    def _is_authorized(self, request: web.Request, *, allow_query_token: bool) -> bool:
        """校验 Bearer Token；浏览器 demo 允许通过 query token 接入。"""
        expected = str(self._config.remote.auth_token or "").strip()
        auth = str(request.headers.get("Authorization", "") or "").strip()
        if auth == f"Bearer {expected}":
            return True
        if not allow_query_token:
            return False
        query_token = (parse_qs(request.query_string).get("token") or [""])[0].strip()
        return bool(query_token) and query_token == expected

    async def _handle_command(self, client: RemoteClient, raw: str) -> None:
        """解析并执行一条客户端命令。"""
        try:
            payload = json.loads(raw)
            command = RemoteCommand.model_validate(payload)
        except Exception as exc:
            await client.send_json(
                build_error_event(
                    f"invalid command: {exc}",
                    code="invalid_command",
                    command="invalid",
                )
            )
            return

        try:
            if command.type == "bind_session":
                session_id = self._require_session_id(command)
                await self._hub.bind_session(client.client_key, session_id)
                await client.send_json(build_session_bound_event(session_id=session_id))
                return
            if command.type == "send_message":
                session_id = self._require_session_id(command)
                if not command.content:
                    raise ValueError("content is required")
                await self._hub.bind_session(client.client_key, session_id)
                await client.send_json(build_turn_started_event(session_id=session_id))
                await self._runtime.send_user_message(
                    session_id,
                    command.content,
                    client_id=command.client_id or client.client_id,
                    metadata=command.metadata,
                )
                return
            if command.type == "interrupt_turn":
                session_id = self._require_session_id(command)
                result = self._runtime.interrupt_session(session_id)
                await client.send_json(build_interrupt_result_event(result))
                return
            if command.type == "get_status":
                session_id = self._require_session_id(command)
                snapshot = await self._runtime.get_status_snapshot(session_id)
                await client.send_json(build_status_result_event(snapshot, session_id=session_id))
                return
            if command.type == "list_sessions":
                result = self._runtime.list_sessions(
                    page_token=command.page_token,
                    page_size=command.page_size,
                    include_archived=command.include_archived,
                )
                await client.send_json(
                    build_session_list_event(
                        sessions=result["sessions"],
                        next_page_token=result["next_page_token"],
                        total_count=result["total_count"],
                    )
                )
                return
            if command.type == "create_session":
                session = self._runtime.create_session(
                    session_id=command.session_id,
                    title=command.title,
                )
                await client.send_json(
                    build_session_created_event(
                        session_id=session["session_id"],
                        title=session.get("title"),
                        created_at_ms=session.get("created_at_ms"),
                    )
                )
                return
            if command.type == "delete_session":
                session_id = self._require_session_id(command)
                if await self._hub.is_session_bound(session_id):
                    raise SessionDeleteForbiddenError(
                        "session is currently bound",
                        session_id=session_id,
                    )
                result = self._runtime.delete_session(session_id)
                await client.send_json(
                    build_session_deleted_event(
                        session_id=result["session_id"],
                        deleted=bool(result["deleted"]),
                    )
                )
                return
            if command.type == "load_history":
                session_id = self._require_session_id(command)
                history = self._runtime.load_session_messages(
                    session_id,
                    limit=command.limit or 100,
                    cursor=command.cursor,
                )
                await client.send_json(
                    build_history_snapshot_event(
                        session_id=session_id,
                        messages=history["messages"],
                        cursor=history["cursor"],
                        next_cursor=history["next_cursor"],
                        total_messages=history["total_messages"],
                    )
                )
                return
            if command.type == "get_sidebar":
                session_id = self._require_session_id(command)
                await self._send_sidebar_snapshot(client, session_id)
                return
            if command.type == "task_create_after":
                session_id = self._require_session_id(command)
                task = self._runtime.create_task_after(
                    session_id,
                    instruction=self._require_text(command.instruction, "instruction"),
                    after_seconds=self._require_int(command.after_seconds, "after_seconds"),
                )
                await self._notify_resource_mutation(
                    client,
                    session_id,
                    resource="task",
                    action="create_after",
                    ok=True,
                    message="已创建延时任务。",
                    task_id=task["id"],
                )
                return
            if command.type == "task_create_at":
                session_id = self._require_session_id(command)
                task = self._runtime.create_task_at(
                    session_id,
                    instruction=self._require_text(command.instruction, "instruction"),
                    at=self._require_text(command.at, "at"),
                )
                await self._notify_resource_mutation(
                    client,
                    session_id,
                    resource="task",
                    action="create_at",
                    ok=True,
                    message="已创建定点任务。",
                    task_id=task["id"],
                )
                return
            if command.type == "task_create_daily":
                session_id = self._require_session_id(command)
                task = self._runtime.create_task_daily(
                    session_id,
                    instruction=self._require_text(command.instruction, "instruction"),
                    daily_time=self._require_text(command.daily_time, "daily_time"),
                )
                await self._notify_resource_mutation(
                    client,
                    session_id,
                    resource="task",
                    action="create_daily",
                    ok=True,
                    message="已创建每日任务。",
                    task_id=task["id"],
                )
                return
            if command.type == "task_create_every":
                session_id = self._require_session_id(command)
                task = self._runtime.create_task_every(
                    session_id,
                    instruction=self._require_text(command.instruction, "instruction"),
                    every_seconds=self._require_int(command.every_seconds, "every_seconds"),
                )
                await self._notify_resource_mutation(
                    client,
                    session_id,
                    resource="task",
                    action="create_every",
                    ok=True,
                    message="已创建循环任务。",
                    task_id=task["id"],
                )
                return
            if command.type == "task_delete":
                session_id = self._require_session_id(command)
                task_id = self._require_text(command.task_id, "task_id")
                deleted = self._runtime.delete_task(task_id)
                await self._notify_resource_mutation(
                    client,
                    session_id,
                    resource="task",
                    action="delete",
                    ok=deleted,
                    message="已删除任务。" if deleted else "找不到任务。",
                    task_id=task_id,
                )
                return
            if command.type == "task_enable":
                await self._handle_task_update(client, command, action="enable")
                return
            if command.type == "task_disable":
                await self._handle_task_update(client, command, action="disable")
                return
            if command.type == "task_update_instruction":
                await self._handle_task_update(client, command, action="update_instruction")
                return
            if command.type == "task_reschedule_after":
                await self._handle_task_update(client, command, action="reschedule_after")
                return
            if command.type == "task_reschedule_at":
                await self._handle_task_update(client, command, action="reschedule_at")
                return
            if command.type == "task_reschedule_daily":
                await self._handle_task_update(client, command, action="reschedule_daily")
                return
            if command.type == "task_reschedule_every":
                await self._handle_task_update(client, command, action="reschedule_every")
                return
            if command.type == "skill_install":
                session_id = self._require_session_id(command)
                source = command.source
                upload_path: Path | None = None
                if command.upload_token:
                    upload_path = self._uploaded_archives.pop(command.upload_token, None)
                    if upload_path is None:
                        raise ValueError("upload_token not found")
                    source = str(upload_path)
                ok, message = self._runtime.install_skill(self._require_text(source, "source"))
                await self._notify_resource_mutation(
                    client,
                    session_id,
                    resource="skill",
                    action="install",
                    ok=ok,
                    message=message,
                )
                if upload_path is not None:
                    upload_path.unlink(missing_ok=True)
                return
            if command.type == "skill_uninstall":
                session_id = self._require_session_id(command)
                skill_name = self._require_text(command.skill_name, "skill_name")
                ok, message = self._runtime.uninstall_skill(skill_name)
                await self._notify_resource_mutation(
                    client,
                    session_id,
                    resource="skill",
                    action="uninstall",
                    ok=ok,
                    message=message,
                    skill_name=skill_name,
                )
                return
            if command.type == "mcp_create":
                session_id = self._require_session_id(command)
                mcp_name = self._require_text(command.mcp_name, "mcp_name")
                await self._runtime.create_mcp_server(mcp_name, command.mcp)
                await self._notify_resource_mutation(
                    client,
                    session_id,
                    resource="mcp",
                    action="create",
                    ok=True,
                    message="已创建 MCP server。",
                    mcp_name=mcp_name,
                )
                return
            if command.type == "mcp_update":
                session_id = self._require_session_id(command)
                mcp_name = self._require_text(command.mcp_name, "mcp_name")
                await self._runtime.update_mcp_server(mcp_name, command.mcp)
                await self._notify_resource_mutation(
                    client,
                    session_id,
                    resource="mcp",
                    action="update",
                    ok=True,
                    message="已更新 MCP server。",
                    mcp_name=mcp_name,
                )
                return
            if command.type == "mcp_delete":
                session_id = self._require_session_id(command)
                mcp_name = self._require_text(command.mcp_name, "mcp_name")
                deleted = await self._runtime.delete_mcp_server(mcp_name)
                await self._notify_resource_mutation(
                    client,
                    session_id,
                    resource="mcp",
                    action="delete",
                    ok=deleted,
                    message="已删除 MCP server。" if deleted else "找不到 MCP server。",
                    mcp_name=mcp_name,
                )
                return
            if command.type == "mcp_enable":
                session_id = self._require_session_id(command)
                mcp_name = self._require_text(command.mcp_name, "mcp_name")
                enabled = await self._runtime.enable_mcp_server(mcp_name)
                await self._notify_resource_mutation(
                    client,
                    session_id,
                    resource="mcp",
                    action="enable",
                    ok=enabled is not None,
                    message="已启用 MCP server。" if enabled else "找不到 MCP server。",
                    mcp_name=mcp_name,
                )
                return
            if command.type == "mcp_disable":
                session_id = self._require_session_id(command)
                mcp_name = self._require_text(command.mcp_name, "mcp_name")
                disabled = await self._runtime.disable_mcp_server(mcp_name)
                await self._notify_resource_mutation(
                    client,
                    session_id,
                    resource="mcp",
                    action="disable",
                    ok=disabled is not None,
                    message="已停用 MCP server。" if disabled else "找不到 MCP server。",
                    mcp_name=mcp_name,
                )
                return
            if command.type == "clear_remote_runtime":
                session_id = self._require_session_id(command)
                await self._runtime.clear_remote_runtime_state()
                await self._notify_resource_mutation(
                    client,
                    session_id,
                    resource="runtime",
                    action="clear_remote_runtime",
                    ok=True,
                    message="已清理远端运行态。",
                )
                return
            raise ValueError(f"unsupported command: {command.type}")
        except (SessionNotFoundError, DuplicateSessionIdError, InvalidPageTokenError, SessionDeleteForbiddenError) as exc:
            await client.send_json(
                build_error_event(
                    str(exc),
                    session_id=getattr(exc, "session_id", None),
                    code=getattr(exc, "code", "session_error"),
                    command=command.type,
                )
            )
        except Exception as exc:
            await client.send_json(
                build_error_event(
                    str(exc),
                    session_id=command.session_id,
                    code="runtime_error",
                    command=command.type,
                )
            )

    async def _handle_task_update(
        self,
        client: RemoteClient,
        command: RemoteCommand,
        *,
        action: str,
    ) -> None:
        """处理任务的启停、改文案和改期。"""
        session_id = self._require_session_id(command)
        task_id = self._require_text(command.task_id, "task_id")
        task = None
        if action == "enable":
            task = self._runtime.enable_task(task_id)
        elif action == "disable":
            task = self._runtime.disable_task(task_id)
        elif action == "update_instruction":
            task = self._runtime.update_task_instruction(
                task_id,
                self._require_text(command.instruction, "instruction"),
            )
        elif action == "reschedule_after":
            task = self._runtime.reschedule_task_after(
                task_id,
                after_seconds=self._require_int(command.after_seconds, "after_seconds"),
            )
        elif action == "reschedule_at":
            task = self._runtime.reschedule_task_at(
                task_id,
                at=self._require_text(command.at, "at"),
            )
        elif action == "reschedule_daily":
            task = self._runtime.reschedule_task_daily(
                task_id,
                daily_time=self._require_text(command.daily_time, "daily_time"),
            )
        elif action == "reschedule_every":
            task = self._runtime.reschedule_task_every(
                task_id,
                every_seconds=self._require_int(command.every_seconds, "every_seconds"),
            )
        ok = task is not None
        verb = {
            "enable": "已启用任务。",
            "disable": "已停用任务。",
            "update_instruction": "已更新任务内容。",
            "reschedule_after": "已更新任务时间。",
            "reschedule_at": "已更新任务时间。",
            "reschedule_daily": "已更新任务时间。",
            "reschedule_every": "已更新任务时间。",
        }[action]
        await self._notify_resource_mutation(
            client,
            session_id,
            resource="task",
            action=action,
            ok=ok,
            message=verb if ok else "找不到任务。",
            task_id=task_id,
        )

    async def _send_sidebar_snapshot(self, client: RemoteClient, session_id: str) -> None:
        """向当前客户端发送一份最新侧栏快照。"""
        await client.send_json(
            build_sidebar_snapshot_event(
                session_id=session_id,
                sidebar=self._runtime.get_sidebar_snapshot(),
            )
        )

    async def _notify_resource_mutation(
        self,
        client: RemoteClient,
        session_id: str,
        *,
        resource: str,
        action: str,
        ok: bool,
        message: str,
        task_id: str | None = None,
        skill_name: str | None = None,
        mcp_name: str | None = None,
    ) -> None:
        """发送资源变更结果，并在成功后广播最新侧栏快照。"""
        await client.send_json(
            build_resource_action_result_event(
                session_id=session_id,
                resource=resource,
                action=action,
                ok=ok,
                message=message,
                task_id=task_id,
                skill_name=skill_name,
                mcp_name=mcp_name,
            )
        )
        if not ok:
            return
        await self._hub.broadcast_to_session(
            session_id,
            build_sidebar_snapshot_event(
                session_id=session_id,
                sidebar=self._runtime.get_sidebar_snapshot(),
            ),
        )

    @staticmethod
    def _require_session_id(command: RemoteCommand) -> str:
        """读取并校验 session_id。"""
        if not command.session_id:
            raise ValueError("session_id is required")
        return command.session_id

    @staticmethod
    def _require_text(value: str | None, field_name: str) -> str:
        """读取并校验必填字符串。"""
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field_name} is required")
        return text

    @staticmethod
    def _require_int(value: int | None, field_name: str) -> int:
        """读取并校验必填整数。"""
        if value is None:
            raise ValueError(f"{field_name} is required")
        return int(value)
