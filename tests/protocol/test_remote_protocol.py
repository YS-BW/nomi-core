"""共享 remote vNext 协议层测试。"""

from __future__ import annotations

import pytest

from nomi_protocol import HTTP_ROUTES, PROTOCOL_VERSION, SSE_EVENT_TYPES
from nomi_protocol.events import SseEventEnvelope
from nomi_protocol.http import CreateTaskRequest, CreateTurnRequest
from nomi_protocol.remote import load_remote_protocol_spec
from nomi_protocol.shared import ApiErrorResponse, TaskSchedule


def test_remote_protocol_spec_matches_python_contract() -> None:
    """共享协议 spec 应与 Python 薄封装保持一致。"""
    spec = load_remote_protocol_spec()

    assert PROTOCOL_VERSION == spec["version"]
    assert list(HTTP_ROUTES) == spec["httpRoutes"]
    assert list(SSE_EVENT_TYPES) == spec["sseEventTypes"]


def test_http_routes_cover_required_v1_surface() -> None:
    """vNext HTTP 路由应覆盖当前 remote 管理面。"""
    required = {
        "GET /v1/bootstrap",
        "POST /v1/sessions/{session_id}/turns",
        "POST /v1/tasks",
        "PUT /v1/providers/active",
        "POST /v1/runtime/reload",
        "GET /v1/events",
    }

    assert required.issubset(set(HTTP_ROUTES))


def test_sse_event_types_cover_session_and_turn_stream() -> None:
    """SSE 事件应覆盖跨 channel session 和 turn 实时更新。"""
    required = {
        "session.message_appended",
        "session.updated",
        "turn.started",
        "turn.delta",
        "turn.completed",
        "task.delivered",
    }

    assert required.issubset(set(SSE_EVENT_TYPES))


def test_create_task_request_accepts_global_target_channels_default() -> None:
    """target_channels 省略时应按全局提醒处理。"""
    request = CreateTaskRequest(
        instruction="明早提醒我量体重",
        schedule=TaskSchedule(kind="cron", expr="0 9 * * *", tz="Asia/Shanghai"),
        source_session_key="desktop:test",
    )

    assert request.target_channels == []


def test_create_turn_request_rejects_unknown_fields() -> None:
    """HTTP schema 应保持严格字段校验。"""
    with pytest.raises(Exception):
        CreateTurnRequest.model_validate({"content": "hello", "unexpected": True})


def test_sse_event_envelope_accepts_known_event_type() -> None:
    """SSE envelope 应能校验已知事件类型。"""
    event = SseEventEnvelope(
        id="evt_test",
        type="session.message_appended",
        created_at_ms=1,
        data={"session_id": "weixin:test"},
    )

    assert event.type == "session.message_appended"


def test_api_error_response_shape() -> None:
    """统一错误模型应保持稳定。"""
    error = ApiErrorResponse(
        error={
            "code": "session_not_found",
            "message": "session not found",
            "details": {"session_id": "desktop:test"},
        }
    )

    assert error.error.code == "session_not_found"
