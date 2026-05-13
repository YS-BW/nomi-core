"""remote SSE 事件 hub。"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any

from aiohttp import web
from loguru import logger

from nomi_protocol.events import SseEventEnvelope


def _now_ms() -> int:
    """返回当前毫秒时间戳。"""
    return int(time.time() * 1000)


@dataclass(slots=True)
class _SseClient:
    """描述一个 SSE 客户端。"""

    key: str
    queue: asyncio.Queue[SseEventEnvelope]


class RemoteEventHub:
    """维护 remote SSE 客户端和短期事件 buffer。"""

    def __init__(self, *, buffer_size: int = 500) -> None:
        """初始化事件 hub。"""
        self._clients: dict[str, _SseClient] = {}
        self._buffer: deque[SseEventEnvelope] = deque(maxlen=buffer_size)
        self._lock = asyncio.Lock()

    async def publish(
        self, event_type: str, data: dict[str, Any] | None = None
    ) -> SseEventEnvelope:
        """发布一条 SSE 事件。"""
        event = SseEventEnvelope(
            id=f"evt_{_now_ms()}_{uuid.uuid4().hex[:8]}",
            type=event_type,
            created_at_ms=_now_ms(),
            data=data or {},
        )
        async with self._lock:
            self._buffer.append(event)
            clients = list(self._clients.values())
        for client in clients:
            try:
                client.queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Drop remote SSE event for slow client {}", client.key)
        return event

    async def register(self) -> _SseClient:
        """注册一个 SSE 客户端。"""
        client = _SseClient(
            key=f"sse-{uuid.uuid4().hex[:12]}",
            queue=asyncio.Queue(maxsize=200),
        )
        async with self._lock:
            self._clients[client.key] = client
        return client

    async def unregister(self, client_key: str) -> None:
        """移除 SSE 客户端。"""
        async with self._lock:
            self._clients.pop(client_key, None)

    async def replay_since(self, last_event_id: str | None) -> tuple[bool, list[SseEventEnvelope]]:
        """返回指定事件之后的 buffer 事件。"""
        normalized = str(last_event_id or "").strip()
        if not normalized:
            return True, []
        async with self._lock:
            items = list(self._buffer)
        for index, item in enumerate(items):
            if item.id == normalized:
                return True, items[index + 1 :]
        return False, []


def format_sse_event(event: SseEventEnvelope) -> bytes:
    """把事件格式化为 SSE wire 文本。"""
    payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.id}\nevent: {event.type}\ndata: {payload}\n\n".encode("utf-8")


def sse_response_headers() -> dict[str, str]:
    """返回 SSE 响应头。"""
    return {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "Access-Control-Allow-Origin": "*",
    }


async def prepare_sse_response(request: web.Request) -> web.StreamResponse:
    """创建并准备 SSE response。"""
    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers=sse_response_headers(),
    )
    await response.prepare(request)
    return response
