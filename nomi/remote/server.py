"""remote vNext HTTP + SSE 服务端。"""

from __future__ import annotations

import asyncio
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiohttp import web
from loguru import logger
from nomi_protocol.events import SseEventEnvelope
from nomi_protocol.http import (
    BootstrapResponse,
    CreateSessionRequest,
    CreateTaskRequest,
    CreateTurnRequest,
    CreateTurnResponse,
    DeleteMcpResponse,
    DeleteSessionResponse,
    DeleteTaskResponse,
    HealthResponse,
    InstallSkillRequest,
    InterruptSessionResponse,
    McpListResponse,
    McpResponse,
    ProviderListResponse,
    ProviderStateResponse,
    RescheduleTaskRequest,
    ResetSessionResponse,
    ResourceActionResponse,
    RuntimeReloadResponse,
    SessionListResponse,
    SessionMessagesResponse,
    SessionResponse,
    SetActiveProviderRequest,
    SetActiveProviderResponse,
    SkillListResponse,
    SkillUploadResponse,
    TaskListResponse,
    TaskResponse,
    UpdateProviderRequest,
    UpdateProviderResponse,
    UpdateTaskRequest,
    UpsertMcpRequest,
)
from pydantic import ValidationError

from nomi import __version__
from nomi.bus.events import OutboundMessage
from nomi.config.schema import Config
from nomi.remote.auth import is_authorized_request
from nomi.remote.errors import RemoteApiError, api_error_response
from nomi.remote.events import RemoteEventHub, format_sse_event, prepare_sse_response
from nomi.runtime import NomiRuntime
from nomi.runtime.errors import RuntimeConfigError
from nomi.session.errors import (
    DuplicateSessionIdError,
    InvalidPageTokenError,
    SessionDeleteForbiddenError,
    SessionError,
    SessionNotFoundError,
)


class RemoteServer:
    """承载 remote vNext HTTP API 与 SSE event stream。"""

    def __init__(self, config: Config, runtime: NomiRuntime) -> None:
        """绑定配置和 runtime。"""
        self._config = config
        self._runtime = runtime
        self._events = RemoteEventHub()
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._unsubscribe_bus: Callable[[], None] | None = None
        self._unsubscribe_sessions: Callable[[], None] | None = None
        self._upload_tempdir = tempfile.TemporaryDirectory(prefix="nomi-remote-skills-")
        self._uploaded_archives: dict[str, Path] = {}

    async def start(self) -> None:
        """启动 HTTP + SSE 服务并注册 runtime 事件订阅。"""
        self._ensure_enabled()
        self._unsubscribe_bus = self._runtime.bus.subscribe_outbound(self._handle_outbound)
        self._subscribe_session_changes()
        self._app = web.Application(middlewares=[self._error_middleware])
        self._register_routes(self._app)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._config.remote.host, self._config.remote.port)
        await self._site.start()
        logger.info(
            "Remote service started at http://{}:{}",
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
        if self._unsubscribe_sessions is not None:
            self._unsubscribe_sessions()
            self._unsubscribe_sessions = None
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

    def _register_routes(self, app: web.Application) -> None:
        """注册 vNext HTTP/SSE 路由。"""
        app.router.add_get("/v1/health", self._handle_health)
        app.router.add_get("/v1/bootstrap", self._handle_bootstrap)
        app.router.add_get("/v1/status", self._handle_status)
        app.router.add_get("/v1/sidebar", self._handle_sidebar)
        app.router.add_get("/v1/events", self._handle_events)

        app.router.add_get("/v1/sessions", self._handle_list_sessions)
        app.router.add_post("/v1/sessions", self._handle_create_session)
        app.router.add_get("/v1/sessions/{session_id}", self._handle_get_session)
        app.router.add_delete("/v1/sessions/{session_id}", self._handle_delete_session)
        app.router.add_get("/v1/sessions/{session_id}/messages", self._handle_session_messages)
        app.router.add_post("/v1/sessions/{session_id}/turns", self._handle_create_turn)
        app.router.add_post("/v1/sessions/{session_id}/interrupt", self._handle_interrupt_session)
        app.router.add_post("/v1/sessions/{session_id}/reset", self._handle_reset_session)

        app.router.add_get("/v1/tasks", self._handle_list_tasks)
        app.router.add_post("/v1/tasks", self._handle_create_task)
        app.router.add_get("/v1/tasks/{task_id}", self._handle_get_task)
        app.router.add_patch("/v1/tasks/{task_id}", self._handle_update_task)
        app.router.add_delete("/v1/tasks/{task_id}", self._handle_delete_task)
        app.router.add_post("/v1/tasks/{task_id}/enable", self._handle_enable_task)
        app.router.add_post("/v1/tasks/{task_id}/disable", self._handle_disable_task)
        app.router.add_post("/v1/tasks/{task_id}/reschedule", self._handle_reschedule_task)

        app.router.add_get("/v1/providers", self._handle_list_providers)
        app.router.add_get("/v1/providers/state", self._handle_provider_state)
        app.router.add_patch("/v1/providers/{provider}", self._handle_update_provider)
        app.router.add_put("/v1/providers/active", self._handle_set_active_provider)
        app.router.add_post("/v1/runtime/reload", self._handle_reload_runtime)
        app.router.add_post("/v1/runtime/clear-remote-state", self._handle_clear_remote_state)

        app.router.add_get("/v1/skills", self._handle_list_skills)
        app.router.add_post("/v1/skills/uploads", self._handle_skill_upload)
        app.router.add_post("/v1/skills", self._handle_install_skill)
        app.router.add_delete("/v1/skills/{skill_name}", self._handle_uninstall_skill)

        app.router.add_get("/v1/mcp", self._handle_list_mcp)
        app.router.add_post("/v1/mcp", self._handle_create_mcp)
        app.router.add_patch("/v1/mcp/{name}", self._handle_update_mcp)
        app.router.add_delete("/v1/mcp/{name}", self._handle_delete_mcp)
        app.router.add_post("/v1/mcp/{name}/enable", self._handle_enable_mcp)
        app.router.add_post("/v1/mcp/{name}/disable", self._handle_disable_mcp)

        app.router.add_post(
            "/v1/instance/relations/request",
            self._handle_instance_relation_request,
        )
        app.router.add_post(
            "/v1/instance/relations/response",
            self._handle_instance_relation_response,
        )
        app.router.add_post("/v1/instance/messages", self._handle_instance_message)

    @web.middleware
    async def _error_middleware(
        self,
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        """把业务异常统一映射为协议层错误响应。"""
        if request.method == "OPTIONS":
            return self._with_cors(web.Response(status=204))
        try:
            return self._with_cors(await handler(request))
        except RemoteApiError as exc:
            return self._with_cors(
                api_error_response(
                    exc.code,
                    exc.message,
                    status=exc.status,
                    details=exc.details,
                )
            )
        except ValidationError as exc:
            return self._with_cors(
                api_error_response(
                    "invalid_request",
                    "invalid request payload",
                    status=400,
                    details={"errors": exc.errors()},
                )
            )
        except (SessionError, RuntimeConfigError) as exc:
            return self._with_cors(
                api_error_response(
                    getattr(exc, "code", "runtime_error"),
                    str(exc),
                    status=self._status_for_error(exc),
                    details=self._details_for_error(exc),
                )
            )
        except ValueError as exc:
            return self._with_cors(api_error_response("invalid_request", str(exc), status=400))
        except PermissionError as exc:
            return self._with_cors(api_error_response("forbidden", str(exc), status=403))
        except web.HTTPException:
            raise
        except Exception as exc:
            logger.exception("Remote API request failed: {} {}", request.method, request.path)
            return self._with_cors(api_error_response("runtime_error", str(exc), status=500))

    async def _handle_health(self, request: web.Request) -> web.Response:
        """返回健康检查结果。"""
        self._authorize(request)
        return self._json(HealthResponse(ok=True, version=__version__))

    async def _handle_bootstrap(self, request: web.Request) -> web.Response:
        """返回 desktop 首屏所需的完整快照。"""
        self._authorize(request)
        return self._json(
            BootstrapResponse.model_validate(await self._runtime.get_bootstrap_snapshot())
        )

    async def _handle_status(self, request: web.Request) -> web.Response:
        """返回 runtime 状态。"""
        self._authorize(request)
        return web.json_response(await self._runtime.get_status_payload())

    async def _handle_sidebar(self, request: web.Request) -> web.Response:
        """返回资源侧栏快照。"""
        self._authorize(request)
        return web.json_response(self._runtime.get_sidebar_snapshot())

    async def _handle_events(self, request: web.Request) -> web.StreamResponse:
        """建立 SSE event stream。"""
        self._authorize(request, allow_query_token=True)
        response = await prepare_sse_response(request)
        client = await self._events.register()
        try:
            ok, replay_events = await self._events.replay_since(
                request.headers.get("Last-Event-ID")
            )
            if not ok:
                resync = SseEventEnvelope(
                    id=f"evt_resync_{uuid.uuid4().hex[:8]}",
                    type="runtime.resync_required",
                    created_at_ms=self._now_ms(),
                    data={"reason": "last_event_id_not_found"},
                )
                await response.write(format_sse_event(resync))
            for event in replay_events:
                await response.write(format_sse_event(event))

            connected = SseEventEnvelope(
                id=f"evt_connected_{uuid.uuid4().hex[:8]}",
                type="runtime.connected",
                created_at_ms=self._now_ms(),
                data={
                    "version": __version__,
                    "provider_state": self._runtime.get_provider_state_snapshot(),
                },
            )
            await response.write(format_sse_event(connected))

            while True:
                try:
                    event = await asyncio.wait_for(client.queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    await response.write(b": heartbeat\n\n")
                    continue
                await response.write(format_sse_event(event))
        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            await self._events.unregister(client.key)
        return response

    async def _handle_list_sessions(self, request: web.Request) -> web.Response:
        """列出会话。"""
        self._authorize(request)
        page_size = self._optional_int(request.query.get("page_size"))
        result = self._runtime.list_sessions(
            page_token=request.query.get("page_token"),
            page_size=page_size,
            include_archived=self._optional_bool(request.query.get("include_archived")),
        )
        return self._json(
            SessionListResponse(
                sessions=result.get("sessions", []),
                page={
                    "next_page_token": result.get("next_page_token"),
                    "total_count": result.get("total_count"),
                },
            )
        )

    async def _handle_create_session(self, request: web.Request) -> web.Response:
        """创建会话。"""
        self._authorize(request)
        payload = CreateSessionRequest.model_validate(await self._read_json(request))
        session = self._runtime.create_session(payload.session_id, title=payload.title)
        await self._events.publish("session.created", {"session": session})
        await self._publish_sidebar_snapshot()
        return self._json(SessionResponse(session=session), status=201)

    async def _handle_get_session(self, request: web.Request) -> web.Response:
        """读取单个会话摘要。"""
        self._authorize(request)
        return self._json(
            SessionResponse(session=self._runtime.get_session(self._path_session_id(request)))
        )

    async def _handle_delete_session(self, request: web.Request) -> web.Response:
        """删除会话。"""
        self._authorize(request)
        result = self._runtime.delete_session(self._path_session_id(request))
        await self._events.publish(
            "session.deleted",
            {"session": {"key": result["session_id"], "session_id": result["session_id"]}},
        )
        await self._publish_sidebar_snapshot()
        return self._json(DeleteSessionResponse(**result))

    async def _handle_session_messages(self, request: web.Request) -> web.Response:
        """读取会话消息。"""
        self._authorize(request)
        limit = self._optional_int(request.query.get("limit")) or 100
        cursor = self._optional_int(request.query.get("cursor"))
        payload = self._runtime.load_session_messages(
            self._path_session_id(request),
            limit=limit,
            cursor=cursor,
        )
        return self._json(SessionMessagesResponse.model_validate(payload))

    async def _handle_create_turn(self, request: web.Request) -> web.Response:
        """创建一轮消息处理；正文通过 SSE 返回。"""
        self._authorize(request)
        payload = CreateTurnRequest.model_validate(await self._read_json(request))
        session_id = self._path_session_id(request)
        result = await self._runtime.create_turn(
            session_id,
            payload.content,
            client_id=payload.client_id or "remote-http",
            metadata=payload.metadata,
        )
        await self._events.publish("turn.started", result)
        return self._json(CreateTurnResponse.model_validate(result), status=202)

    async def _handle_interrupt_session(self, request: web.Request) -> web.Response:
        """中断指定会话的当前 turn。"""
        self._authorize(request)
        session_id = self._path_session_id(request)
        result = self._runtime.interrupt_session(session_id)
        payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else dict(result)
        await self._events.publish(
            "turn.interrupted",
            {
                "turn_id": None,
                "session_id": session_id,
                "stop_reason": payload.get("reason") or "interrupted",
                "error": None,
            },
        )
        return self._json(InterruptSessionResponse(session_id=session_id, result=payload))

    async def _handle_reset_session(self, request: web.Request) -> web.Response:
        """重置指定会话。"""
        self._authorize(request)
        session_id = self._path_session_id(request)
        self._runtime.reset_session(session_id)
        await self._events.publish(
            "session.updated", {"session": self._runtime.get_session(session_id)}
        )
        return self._json(ResetSessionResponse(session_id=session_id, reset=True))

    async def _handle_list_tasks(self, request: web.Request) -> web.Response:
        """列出任务。"""
        self._authorize(request)
        return self._json(TaskListResponse(tasks=self._runtime.list_task_items()))

    async def _handle_create_task(self, request: web.Request) -> web.Response:
        """创建任务。"""
        self._authorize(request)
        payload = CreateTaskRequest.model_validate(await self._read_json(request))
        task = self._runtime.create_task_from_schedule(
            instruction=payload.instruction,
            schedule=self._runtime.schedule_from_remote_payload(payload.schedule),
            source_session_key=payload.source_session_key,
            target_channels=payload.target_channels,
        )
        await self._events.publish("task.created", {"task": task})
        await self._publish_sidebar_snapshot()
        return self._json(TaskResponse(task=task), status=201)

    async def _handle_get_task(self, request: web.Request) -> web.Response:
        """读取任务。"""
        self._authorize(request)
        task = self._require_task(request.match_info["task_id"])
        return self._json(TaskResponse(task=task))

    async def _handle_update_task(self, request: web.Request) -> web.Response:
        """更新任务内容、调度或投递目标。"""
        self._authorize(request)
        task_id = request.match_info["task_id"]
        payload = UpdateTaskRequest.model_validate(await self._read_json(request))
        task = None
        if payload.instruction is not None:
            task = self._runtime.update_task_instruction(task_id, payload.instruction)
        if payload.schedule is not None:
            task = self._update_task_schedule(task_id, payload.schedule)
        if payload.target_channels is not None:
            task = self._update_task_target_channels(task_id, payload.target_channels)
        if task is None:
            task = self._require_task(task_id)
        await self._events.publish("task.updated", {"task": task})
        await self._publish_sidebar_snapshot()
        return self._json(TaskResponse(task=task))

    async def _handle_delete_task(self, request: web.Request) -> web.Response:
        """删除任务。"""
        self._authorize(request)
        task_id = request.match_info["task_id"]
        deleted = self._runtime.delete_task(task_id)
        await self._events.publish("task.deleted", {"task_id": task_id})
        await self._publish_sidebar_snapshot()
        return self._json(DeleteTaskResponse(task_id=task_id, deleted=deleted))

    async def _handle_enable_task(self, request: web.Request) -> web.Response:
        """启用任务。"""
        self._authorize(request)
        task = self._require_existing_result(
            self._runtime.enable_task(request.match_info["task_id"]),
            "task_not_found",
            "task not found",
        )
        await self._events.publish("task.updated", {"task": task})
        await self._publish_sidebar_snapshot()
        return self._json(TaskResponse(task=task))

    async def _handle_disable_task(self, request: web.Request) -> web.Response:
        """停用任务。"""
        self._authorize(request)
        task = self._require_existing_result(
            self._runtime.disable_task(request.match_info["task_id"]),
            "task_not_found",
            "task not found",
        )
        await self._events.publish("task.updated", {"task": task})
        await self._publish_sidebar_snapshot()
        return self._json(TaskResponse(task=task))

    async def _handle_reschedule_task(self, request: web.Request) -> web.Response:
        """重排任务。"""
        self._authorize(request)
        payload = RescheduleTaskRequest.model_validate(await self._read_json(request))
        task = self._update_task_schedule(request.match_info["task_id"], payload.schedule)
        await self._events.publish("task.updated", {"task": task})
        await self._publish_sidebar_snapshot()
        return self._json(TaskResponse(task=task))

    async def _handle_list_providers(self, request: web.Request) -> web.Response:
        """列出 provider。"""
        self._authorize(request)
        return self._json(ProviderListResponse(provider_list=self._runtime.list_providers()))

    async def _handle_provider_state(self, request: web.Request) -> web.Response:
        """读取 provider 状态。"""
        self._authorize(request)
        return self._json(
            ProviderStateResponse(provider_state=self._runtime.get_provider_state_snapshot())
        )

    async def _handle_update_provider(self, request: web.Request) -> web.Response:
        """更新 provider 配置。"""
        self._authorize(request)
        payload = UpdateProviderRequest.model_validate(await self._read_json(request))
        fields = payload.model_fields_set
        result = self._runtime.update_provider(
            request.match_info["provider"],
            api_key=payload.api_key if "api_key" in fields else Ellipsis,
            token_plan_api_key=(
                payload.token_plan_api_key if "token_plan_api_key" in fields else Ellipsis
            ),
            api_base=payload.api_base if "api_base" in fields else Ellipsis,
            model=payload.model if "model" in fields else Ellipsis,
            clear_api_key=payload.clear_api_key if "clear_api_key" in fields else Ellipsis,
            clear_token_plan_api_key=(
                payload.clear_token_plan_api_key
                if "clear_token_plan_api_key" in fields
                else Ellipsis
            ),
        )
        await self._events.publish(
            "provider.settings_updated",
            {
                "provider": result["provider"],
                "settings": result["settings"],
                "requires_runtime_reload": result["requires_runtime_reload"],
            },
        )
        await self._events.publish(
            "provider.state_changed",
            {"provider_state": self._runtime.get_provider_state_snapshot()},
        )
        return self._json(UpdateProviderResponse.model_validate(result))

    async def _handle_set_active_provider(self, request: web.Request) -> web.Response:
        """切换 active provider。"""
        self._authorize(request)
        payload = SetActiveProviderRequest.model_validate(await self._read_json(request))
        result = self._runtime.set_active_provider(payload.provider, model=payload.model)
        await self._events.publish(
            "provider.active_changed",
            {
                "active": result["active"],
                "requires_runtime_reload": result["requires_runtime_reload"],
            },
        )
        await self._events.publish(
            "provider.state_changed",
            {"provider_state": self._runtime.get_provider_state_snapshot()},
        )
        return self._json(SetActiveProviderResponse.model_validate(result))

    async def _handle_reload_runtime(self, request: web.Request) -> web.Response:
        """重载 runtime。"""
        self._authorize(request)
        result = await self._runtime.reload_runtime()
        self._subscribe_session_changes()
        await self._events.publish("runtime.reloaded", result)
        await self._events.publish(
            "provider.state_changed", {"provider_state": result["provider_state"]}
        )
        return self._json(RuntimeReloadResponse.model_validate(result))

    async def _handle_clear_remote_state(self, request: web.Request) -> web.Response:
        """清理远端运行态。"""
        self._authorize(request)
        await self._runtime.clear_remote_runtime_state()
        await self._publish_sidebar_snapshot()
        return self._json(
            ResourceActionResponse(
                ok=True,
                message="已清理远端运行态。",
                resource="runtime",
                action="clear_remote_state",
            )
        )

    async def _handle_list_skills(self, request: web.Request) -> web.Response:
        """列出 skills。"""
        self._authorize(request)
        return self._json(SkillListResponse(skills=self._runtime.list_skills()))

    async def _handle_skill_upload(self, request: web.Request) -> web.Response:
        """上传 skill zip 包。"""
        self._authorize(request)
        filename = str(request.headers.get("X-Skill-Filename", "") or "").strip()
        body = b""
        content_type = str(request.headers.get("Content-Type", "") or "")
        if content_type.startswith("multipart/form-data"):
            reader = await request.multipart()
            field = await reader.next()
            if field is None or field.name != "file":
                raise RemoteApiError("invalid_upload", "file field is required", status=400)
            filename = filename or str(field.filename or "").strip()
            body = await field.read(decode=False)
        else:
            body = await request.read()

        if not filename.lower().endswith(".zip"):
            raise RemoteApiError(
                "invalid_upload", "only .zip skill packages are supported", status=400
            )
        if not body:
            raise RemoteApiError("invalid_upload", "empty upload", status=400)

        upload_token = f"upload_{uuid.uuid4().hex[:16]}"
        target = Path(self._upload_tempdir.name) / f"{upload_token}.zip"
        target.write_bytes(body)
        self._uploaded_archives[upload_token] = target
        return self._json(
            SkillUploadResponse(ok=True, upload_token=upload_token, filename=filename)
        )

    async def _handle_install_skill(self, request: web.Request) -> web.Response:
        """安装 skill。"""
        self._authorize(request)
        payload = InstallSkillRequest.model_validate(await self._read_json(request))
        source = payload.source
        upload_path: Path | None = None
        if payload.upload_token:
            upload_path = self._uploaded_archives.pop(payload.upload_token, None)
            if upload_path is None:
                raise RemoteApiError("upload_not_found", "upload_token not found", status=404)
            source = str(upload_path)
        if not source:
            raise RemoteApiError(
                "invalid_request", "source or upload_token is required", status=400
            )
        ok, message = self._runtime.install_skill(source)
        if upload_path is not None:
            upload_path.unlink(missing_ok=True)
        await self._events.publish(
            "skill.installed", {"resource": "skill", "action": "install", "name": source}
        )
        await self._publish_sidebar_snapshot()
        return self._json(
            ResourceActionResponse(
                ok=ok, message=message, resource="skill", action="install", id=source
            )
        )

    async def _handle_uninstall_skill(self, request: web.Request) -> web.Response:
        """卸载 skill。"""
        self._authorize(request)
        skill_name = request.match_info["skill_name"]
        ok, message = self._runtime.uninstall_skill(skill_name)
        await self._events.publish(
            "skill.uninstalled",
            {"resource": "skill", "action": "uninstall", "name": skill_name},
        )
        await self._publish_sidebar_snapshot()
        return self._json(
            ResourceActionResponse(
                ok=ok, message=message, resource="skill", action="uninstall", id=skill_name
            )
        )

    async def _handle_list_mcp(self, request: web.Request) -> web.Response:
        """列出 MCP servers。"""
        self._authorize(request)
        return self._json(
            McpListResponse(
                mcp_servers=[
                    self._normalize_mcp_item(item) for item in self._runtime.list_mcp_servers()
                ]
            )
        )

    async def _handle_create_mcp(self, request: web.Request) -> web.Response:
        """创建 MCP server。"""
        self._authorize(request)
        body = await self._read_json(request)
        name = str(body.get("name") or body.get("mcp_name") or "").strip()
        payload = self._extract_mcp_payload(body)
        if not name:
            raise RemoteApiError("invalid_request", "name is required", status=400)
        item = self._normalize_mcp_item(await self._runtime.create_mcp_server(name, payload))
        await self._events.publish(
            "mcp.created", {"resource": "mcp", "action": "create", "name": name, "item": item}
        )
        await self._publish_sidebar_snapshot()
        return self._json(McpResponse(mcp=item), status=201)

    async def _handle_update_mcp(self, request: web.Request) -> web.Response:
        """更新 MCP server。"""
        self._authorize(request)
        name = request.match_info["name"]
        item = self._normalize_mcp_item(
            await self._runtime.update_mcp_server(
                name, self._extract_mcp_payload(await self._read_json(request))
            )
        )
        await self._events.publish(
            "mcp.updated", {"resource": "mcp", "action": "update", "name": name, "item": item}
        )
        await self._publish_sidebar_snapshot()
        return self._json(McpResponse(mcp=item))

    async def _handle_delete_mcp(self, request: web.Request) -> web.Response:
        """删除 MCP server。"""
        self._authorize(request)
        name = request.match_info["name"]
        deleted = await self._runtime.delete_mcp_server(name)
        await self._events.publish(
            "mcp.deleted", {"resource": "mcp", "action": "delete", "name": name}
        )
        await self._publish_sidebar_snapshot()
        return self._json(DeleteMcpResponse(name=name, deleted=deleted))

    async def _handle_enable_mcp(self, request: web.Request) -> web.Response:
        """启用 MCP server。"""
        self._authorize(request)
        name = request.match_info["name"]
        item = self._normalize_mcp_item(
            self._require_existing_result(
                await self._runtime.enable_mcp_server(name),
                "mcp_not_found",
                "MCP server not found",
            )
        )
        await self._events.publish(
            "mcp.enabled", {"resource": "mcp", "action": "enable", "name": name, "item": item}
        )
        await self._publish_sidebar_snapshot()
        return self._json(McpResponse(mcp=item))

    async def _handle_disable_mcp(self, request: web.Request) -> web.Response:
        """停用 MCP server。"""
        self._authorize(request)
        name = request.match_info["name"]
        item = self._normalize_mcp_item(
            self._require_existing_result(
                await self._runtime.disable_mcp_server(name),
                "mcp_not_found",
                "MCP server not found",
            )
        )
        await self._events.publish(
            "mcp.disabled", {"resource": "mcp", "action": "disable", "name": name, "item": item}
        )
        await self._publish_sidebar_snapshot()
        return self._json(McpResponse(mcp=item))

    async def _handle_instance_relation_request(self, request: web.Request) -> web.Response:
        """处理 instance 好友申请。"""
        invite_id = str(request.headers.get("X-Nomi-Invite-Id") or "").strip()
        invite_secret = self._bearer_token(request)
        if not invite_id or not invite_secret:
            raise RemoteApiError("unauthorized", "invalid instance invite credentials", status=401)
        result = await self._runtime.receive_instance_relation_request(
            await self._read_json(request),
            invite_id=invite_id,
            invite_secret=invite_secret,
        )
        return web.json_response(result)

    async def _handle_instance_relation_response(self, request: web.Request) -> web.Response:
        """处理 instance 好友申请确认结果。"""
        token = self._bearer_token(request)
        if not token:
            raise RemoteApiError(
                "unauthorized",
                "missing instance relation credentials",
                status=401,
            )
        relation_id = str(request.headers.get("X-Nomi-Relation-Id") or "").strip() or None
        result = await self._runtime.receive_instance_relation_response(
            await self._read_json(request),
            response_token=token if relation_id is None else None,
            relation_id=relation_id,
            relation_token=token if relation_id is not None else None,
        )
        return web.json_response(result)

    async def _handle_instance_message(self, request: web.Request) -> web.Response:
        """处理 instance 聊天消息。"""
        relation_id = str(request.headers.get("X-Nomi-Relation-Id") or "").strip()
        relation_token = self._bearer_token(request)
        if not relation_id or not relation_token:
            raise RemoteApiError(
                "unauthorized",
                "missing instance relation credentials",
                status=401,
            )
        result = await self._runtime.receive_instance_message(
            await self._read_json(request),
            relation_id=relation_id,
            relation_token=relation_token,
        )
        return web.json_response(result)

    async def _handle_outbound(self, message: OutboundMessage) -> None:
        """把 runtime outbound 转换为 SSE 事件。"""
        metadata = dict(message.metadata or {})
        session_id = str(metadata.get("_session_id") or f"{message.channel}:{message.chat_id}")
        turn_id = metadata.get("_turn_id")
        if metadata.get("_task_delivery_id") and metadata.get("_global_reminder_broadcast"):
            return
        if metadata.get("_task_delivery_id"):
            await self._events.publish(
                "task.delivered",
                {
                    "task_id": str(metadata.get("_task_delivery_id")),
                    "content": message.content,
                    "session_id": session_id,
                },
            )
            return
        if metadata.get("_tool_transition"):
            await self._events.publish(
                "turn.progress",
                {
                    "turn_id": turn_id,
                    "session_id": session_id,
                    "content": message.content,
                    "tool_hint": True,
                },
            )
            return
        if metadata.get("_progress"):
            await self._events.publish(
                "turn.progress",
                {
                    "turn_id": turn_id,
                    "session_id": session_id,
                    "content": message.content,
                    "tool_hint": False,
                },
            )
            return
        if metadata.get("_stream_delta"):
            await self._events.publish(
                "turn.delta",
                {
                    "turn_id": turn_id,
                    "session_id": session_id,
                    "content": message.content,
                    "tool_hint": False,
                },
            )
            return
        if metadata.get("_stream_end"):
            await self._events.publish(
                "turn.stream_end",
                {
                    "turn_id": turn_id,
                    "session_id": session_id,
                    "resuming": bool(metadata.get("_resuming")),
                },
            )
            return
        if metadata.get("_interrupted"):
            event_type = "turn.interrupted"
        elif metadata.get("_failed"):
            event_type = "turn.failed"
        else:
            event_type = "turn.completed"
        await self._events.publish(
            event_type,
            {
                "turn_id": turn_id,
                "session_id": session_id,
                "stop_reason": self._resolve_stop_reason(metadata),
                "error": metadata.get("_error"),
            },
        )

    def _subscribe_session_changes(self) -> None:
        """订阅当前 runtime session 持久化事件。"""
        if self._unsubscribe_sessions is not None:
            self._unsubscribe_sessions()
            self._unsubscribe_sessions = None
        agent_loop = getattr(self._runtime, "agent_loop", None)
        sessions = getattr(agent_loop, "sessions", None)
        subscribe = getattr(sessions, "subscribe_changes", None)
        if not callable(subscribe):
            return

        def _on_saved(_action: str, session, new_messages: list[dict[str, Any]]) -> None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            loop.create_task(self._publish_session_saved(session, new_messages))

        self._unsubscribe_sessions = subscribe(_on_saved)

    async def _publish_session_saved(self, session, new_messages: list[dict[str, Any]]) -> None:
        """发布 session 保存后的增量事件。"""
        summary = self._runtime.get_session(session.key)
        start_index = len(session.messages) - len(new_messages)
        for offset, message in enumerate(new_messages):
            await self._events.publish(
                "session.message_appended",
                {
                    "session_id": session.key,
                    "message": self._serialize_session_message(message),
                    "index": start_index + offset,
                },
            )
        await self._events.publish("session.updated", {"session": summary})

    async def _publish_sidebar_snapshot(self) -> None:
        """广播资源侧栏刷新事件。"""
        sidebar = self._runtime.get_sidebar_snapshot()
        await self._events.publish("sidebar.invalidated", {})
        await self._events.publish("sidebar.snapshot", {"sidebar": sidebar})

    def _update_task_schedule(self, task_id: str, schedule) -> dict:
        """按协议调度结构更新任务。"""
        if schedule.kind == "at":
            if schedule.at_ms is None:
                raise RemoteApiError("invalid_request", "schedule.at_ms is required", status=400)
            task = self._runtime.agent_loop.tasks.update_task(
                task_id,
                schedule=self._runtime.schedule_from_remote_payload(schedule),
                turn=1,
                update_turn=True,
            )
        elif schedule.kind in {"every", "cron"}:
            task = self._runtime.agent_loop.tasks.update_task(
                task_id,
                schedule=self._runtime.schedule_from_remote_payload(schedule),
                turn=None,
                update_turn=True,
            )
        else:
            task = None
        return self._require_existing_result(
            task and self._runtime.get_task_item(task_id),
            "task_not_found",
            "task not found",
        )

    def _update_task_target_channels(self, task_id: str, target_channels: list[str]) -> dict:
        """更新任务显式投递目标。"""
        task = self._runtime.agent_loop.tasks.get_task(task_id)
        if task is None:
            raise RemoteApiError("task_not_found", "task not found", status=404)
        task.target_channels = self._runtime.agent_loop.tasks.normalize_target_channels(
            target_channels
        )
        self._runtime.agent_loop.tasks.store.update_task(task)
        self._runtime.agent_loop.tasks.reconcile_scheduled_jobs()
        return self._require_task(task_id)

    def _require_task(self, task_id: str) -> dict:
        """读取任务，不存在时返回 404。"""
        return self._require_existing_result(
            self._runtime.get_task_item(task_id),
            "task_not_found",
            "task not found",
        )

    @staticmethod
    def _extract_mcp_payload(body: dict[str, Any]) -> dict[str, Any]:
        """从 MCP HTTP 请求中提取配置体。"""
        raw_payload = body.get("mcp") if "mcp" in body else body
        if not isinstance(raw_payload, dict):
            raise RemoteApiError("invalid_request", "mcp must be an object", status=400)
        payload = {
            key: value for key, value in raw_payload.items() if key not in {"name", "mcp_name"}
        }
        return UpsertMcpRequest.model_validate({"mcp": payload}).mcp

    @staticmethod
    def _normalize_mcp_item(item: dict[str, Any]) -> dict[str, Any]:
        """把 runtime/sidebar MCP 结构转换为协议层 McpServerItem。"""
        return {
            "name": str(item.get("name") or ""),
            "enabled": bool(item.get("enabled", False)),
            "type": item.get("type") or item.get("transport"),
            "command": str(item.get("command") or ""),
            "args": list(item.get("args") or []),
            "url": str(item.get("url") or ""),
            "enabled_tools": list(item.get("enabled_tools") or item.get("enabledTools") or []),
            "env": dict(item.get("env") or {}),
            "headers": dict(item.get("headers") or {}),
        }

    @staticmethod
    def _serialize_session_message(message: dict[str, Any]) -> dict[str, Any]:
        """把 session 原始消息裁剪为协议层消息。"""
        allowed = {
            "role",
            "content",
            "timestamp",
            "tool_calls",
            "tool_call_id",
            "name",
            "reasoning_content",
            "reasoning_items",
            "thinking_blocks",
        }
        return {key: value for key, value in dict(message).items() if key in allowed}

    def _authorize(self, request: web.Request, *, allow_query_token: bool = False) -> None:
        """校验当前请求的 remote token。"""
        if is_authorized_request(
            request,
            expected_token=str(self._config.remote.auth_token or ""),
            allow_query_token=allow_query_token,
        ):
            return
        raise RemoteApiError("unauthorized", "unauthorized", status=401)

    @staticmethod
    def _bearer_token(request: web.Request) -> str:
        """读取 Authorization Bearer token。"""
        auth = str(request.headers.get("Authorization", "") or "").strip()
        prefix = "Bearer "
        if not auth.startswith(prefix):
            return ""
        return auth[len(prefix) :].strip()

    @staticmethod
    async def _read_json(request: web.Request) -> dict[str, Any]:
        """读取 JSON 请求体。"""
        if request.can_read_body:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise RemoteApiError(
                    "invalid_request", "request body must be a JSON object", status=400
                )
            return payload
        return {}

    @staticmethod
    def _json(model, *, status: int = 200) -> web.Response:
        """返回 Pydantic 模型 JSON 响应。"""
        payload = model.model_dump(mode="json") if hasattr(model, "model_dump") else model
        return web.json_response(payload, status=status)

    @staticmethod
    def _with_cors(response: web.StreamResponse) -> web.StreamResponse:
        """给 remote HTTP/SSE 响应补充浏览器跨源访问头。"""
        response.headers.setdefault("Access-Control-Allow-Origin", "*")
        response.headers.setdefault(
            "Access-Control-Allow-Headers",
            "Authorization, Content-Type, X-Nomi-Invite-Id, X-Nomi-Relation-Id",
        )
        response.headers.setdefault(
            "Access-Control-Allow-Methods",
            "GET, POST, PATCH, PUT, DELETE, OPTIONS",
        )
        return response

    @staticmethod
    def _path_session_id(request: web.Request) -> str:
        """读取 path 中的 session_id。"""
        return request.match_info["session_id"]

    @staticmethod
    def _instance_relation_credentials(request: web.Request) -> tuple[str, str]:
        """读取 instance relation token 鉴权头。"""
        relation_id = str(request.headers.get("X-Nomi-Relation-Id") or "").strip()
        relation_token = RemoteServer._bearer_token(request)
        if not relation_id or not relation_token:
            raise RemoteApiError(
                "unauthorized",
                "missing instance relation credentials",
                status=401,
            )
        return relation_id, relation_token

    @staticmethod
    def _optional_int(value: str | None) -> int | None:
        """解析可选整数。"""
        if value is None or str(value).strip() == "":
            return None
        return int(value)

    @staticmethod
    def _optional_bool(value: str | None) -> bool | None:
        """解析可选布尔值。"""
        if value is None or str(value).strip() == "":
            return None
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _require_existing_result(value, code: str, message: str):
        """校验可空结果存在。"""
        if value is None:
            raise RemoteApiError(code, message, status=404)
        return value

    @staticmethod
    def _status_for_error(exc: Exception) -> int:
        """按结构化错误类型映射 HTTP 状态码。"""
        if isinstance(exc, SessionNotFoundError):
            return 404
        if isinstance(exc, DuplicateSessionIdError):
            return 409
        if isinstance(exc, SessionDeleteForbiddenError):
            return 409
        if isinstance(exc, InvalidPageTokenError):
            return 400
        return 400

    @staticmethod
    def _details_for_error(exc: Exception) -> dict[str, Any]:
        """提取结构化错误详情。"""
        details: dict[str, Any] = {}
        session_id = getattr(exc, "session_id", None)
        if session_id:
            details["session_id"] = session_id
        fields = getattr(exc, "fields", None)
        if fields:
            details["fields"] = fields
        return details

    @staticmethod
    def _resolve_stop_reason(metadata: dict[str, Any]) -> str:
        """根据出站元数据推断 turn 收尾原因。"""
        if metadata.get("_interrupted"):
            return str(metadata.get("_interrupt_reason") or "interrupted")
        if metadata.get("_task_delivery_id"):
            return "task_delivered"
        if metadata.get("_stop_reason"):
            return str(metadata.get("_stop_reason"))
        return "completed"

    @staticmethod
    def _now_ms() -> int:
        """返回当前毫秒时间戳。"""
        return int(time.time() * 1000)
