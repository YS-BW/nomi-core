"""把 runtime/bus 事件桥接成远程 shell 事件。"""

from __future__ import annotations

from typing import Any

from nomi.bus.events import OutboundMessage
from nomi.remote.hub import RemoteHub
from nomi.runtime.protocol import (
    build_delta_event,
    build_message_event,
    build_progress_event,
    build_stream_end_event,
    build_task_delivered_event,
    build_turn_completed_event,
)


class RemoteBridge:
    """负责把出站消息转发给远程客户端。"""

    def __init__(self, hub: RemoteHub) -> None:
        """绑定连接 hub。"""
        self._hub = hub

    async def handle_outbound(self, message: OutboundMessage) -> None:
        """把一条出站消息转换成远程事件。"""
        if message.channel not in {"remote", "desktop"}:
            return
        metadata = dict(message.metadata or {})
        session_id = str(metadata.get("_session_id") or f"{message.channel}:{message.chat_id}")
        if metadata.get("_task_delivery_id"):
            payload = build_task_delivered_event(
                session_id=session_id,
                task_id=str(metadata.get("_task_delivery_id")),
                content=message.content,
            )
            if metadata.get("_global_reminder_broadcast"):
                await self._hub.broadcast_all(payload)
            else:
                await self._hub.broadcast_to_session(session_id, payload)
            return
        if metadata.get("_tool_transition"):
            await self._hub.broadcast_to_session(
                session_id,
                build_progress_event(
                    session_id=session_id,
                    content=message.content,
                    tool_hint=True,
                ),
            )
            return
        if metadata.get("_progress"):
            await self._hub.broadcast_to_session(
                session_id,
                build_progress_event(
                    session_id=session_id,
                    content=message.content,
                    tool_hint=False,
                ),
            )
            return
        if metadata.get("_stream_delta"):
            await self._hub.broadcast_to_session(
                session_id,
                build_delta_event(session_id=session_id, content=message.content),
            )
            return
        if metadata.get("_stream_end"):
            await self._hub.broadcast_to_session(
                session_id,
                build_stream_end_event(
                    session_id=session_id,
                    resuming=bool(metadata.get("_resuming")),
                ),
            )
            return
        await self._hub.broadcast_to_session(
            session_id,
            build_message_event(session_id=session_id, message=message),
        )
        await self._hub.broadcast_to_session(
            session_id,
            build_turn_completed_event(
                session_id=session_id,
                stop_reason=self._resolve_stop_reason(metadata),
            ),
        )

    @staticmethod
    def _resolve_stop_reason(metadata: dict[str, Any]) -> str:
        """根据出站元数据推断本轮收尾原因。"""
        if metadata.get("_interrupted"):
            return str(metadata.get("_interrupt_reason") or "interrupted")
        if metadata.get("_task_delivery_id"):
            return "task_delivered"
        return "completed"
