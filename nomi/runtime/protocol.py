"""对外脚本化入口共享的 JSON 协议辅助函数。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from nomi.bus.events import OutboundMessage
from nomi.runtime.models import InterruptResult, RuntimeStatusSnapshot


def default_session_id(channel: str, chat_id: str) -> str:
    """返回默认会话键。"""
    return f"{channel}:{chat_id}"


def build_ready_event(**payload: Any) -> dict[str, Any]:
    """构造 ready 事件。"""
    return {"type": "ready", **payload}


def build_session_bound_event(*, session_id: str) -> dict[str, Any]:
    """构造 session 绑定完成事件。"""
    return {"type": "session_bound", "session_id": session_id}


def build_turn_started_event(*, session_id: str) -> dict[str, Any]:
    """构造 turn 开始事件。"""
    return {"type": "turn_started", "session_id": session_id}


def build_progress_event(
    *,
    session_id: str,
    content: str,
    tool_hint: bool = False,
) -> dict[str, Any]:
    """构造进度事件。"""
    return {
        "type": "progress",
        "session_id": session_id,
        "content": content,
        "tool_hint": tool_hint,
    }


def build_delta_event(*, session_id: str, content: str) -> dict[str, Any]:
    """构造正文增量事件。"""
    return {
        "type": "delta",
        "session_id": session_id,
        "content": content,
    }


def build_stream_end_event(*, session_id: str, resuming: bool) -> dict[str, Any]:
    """构造流式收尾事件。"""
    return {
        "type": "stream_end",
        "session_id": session_id,
        "resuming": resuming,
    }


def build_message_event(
    *,
    session_id: str,
    message: OutboundMessage,
) -> dict[str, Any]:
    """构造最终消息事件。"""
    return {
        "type": "message",
        "session_id": session_id,
        "content": message.content,
        "reply_to": message.reply_to,
        "media": list(message.media),
        "metadata": dict(message.metadata or {}),
    }


def build_turn_completed_event(
    *,
    session_id: str,
    stop_reason: str,
) -> dict[str, Any]:
    """构造 turn 完成事件。"""
    return {
        "type": "turn_completed",
        "session_id": session_id,
        "stop_reason": stop_reason,
    }


def build_error_event(message: str, *, session_id: str | None = None) -> dict[str, Any]:
    """构造错误事件。"""
    payload: dict[str, Any] = {"type": "error", "message": message}
    if session_id is not None:
        payload["session_id"] = session_id
    return payload


def build_interrupt_result_event(result: InterruptResult) -> dict[str, Any]:
    """构造中断结果事件。"""
    return {
        "type": "interrupt_result",
        "session_id": result.session_id,
        "result": asdict(result),
    }


def build_reset_done_event(*, session_id: str) -> dict[str, Any]:
    """构造会话重置完成事件。"""
    return {"type": "reset_done", "session_id": session_id}


def build_status_result_event(snapshot: RuntimeStatusSnapshot, *, session_id: str) -> dict[str, Any]:
    """构造状态快照事件。"""
    return {
        "type": "status_result",
        "session_id": session_id,
        "snapshot": asdict(snapshot),
    }


def build_history_snapshot_event(
    *,
    session_id: str,
    messages: list[dict[str, Any]],
    cursor: int,
    next_cursor: int | None,
    total_messages: int,
) -> dict[str, Any]:
    """构造历史消息快照事件。"""
    return {
        "type": "history_snapshot",
        "session_id": session_id,
        "messages": messages,
        "cursor": cursor,
        "next_cursor": next_cursor,
        "total_messages": total_messages,
    }


def build_session_list_event(*, sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """构造会话列表事件。"""
    return {"type": "session_list", "sessions": sessions}


def build_sidebar_snapshot_event(
    *,
    session_id: str,
    sidebar: dict[str, Any],
) -> dict[str, Any]:
    """构造远端资源面快照事件。"""
    return {
        "type": "sidebar_snapshot",
        "session_id": session_id,
        "sidebar": sidebar,
    }


def build_resource_action_result_event(
    *,
    session_id: str,
    resource: str,
    action: str,
    ok: bool,
    message: str,
    task_id: str | None = None,
    skill_name: str | None = None,
    mcp_name: str | None = None,
) -> dict[str, Any]:
    """构造资源管理动作结果事件。"""
    payload: dict[str, Any] = {
        "type": "resource_action_result",
        "session_id": session_id,
        "resource": resource,
        "action": action,
        "ok": ok,
        "message": message,
    }
    if task_id:
        payload["task_id"] = task_id
    if skill_name:
        payload["skill_name"] = skill_name
    if mcp_name:
        payload["mcp_name"] = mcp_name
    return payload


def build_task_delivered_event(
    *,
    session_id: str,
    task_id: str,
    content: str,
) -> dict[str, Any]:
    """构造任务最终投递事件。"""
    return {
        "type": "task_delivered",
        "session_id": session_id,
        "task_id": task_id,
        "content": content,
    }
