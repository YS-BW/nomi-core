"""远程客户端连接管理。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RemoteClient:
    """描述一条已连接的远程客户端。"""

    client_key: str
    client_id: str
    send_json_fn: Callable[[dict[str, Any]], Awaitable[None]]
    bound_sessions: set[str] = field(default_factory=set)

    async def send_json(self, payload: dict[str, Any]) -> None:
        """向客户端发送一条 JSON 事件。"""
        await self.send_json_fn(payload)


class RemoteHub:
    """管理远程客户端与会话订阅关系。"""

    def __init__(self) -> None:
        """初始化连接池。"""
        self._clients: dict[str, RemoteClient] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        client_key: str,
        *,
        client_id: str,
        send_json: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> RemoteClient:
        """注册一条新连接。"""
        client = RemoteClient(client_key=client_key, client_id=client_id, send_json_fn=send_json)
        async with self._lock:
            self._clients[client_key] = client
        return client

    async def unregister(self, client_key: str) -> None:
        """移除一条连接。"""
        async with self._lock:
            self._clients.pop(client_key, None)

    async def bind_session(self, client_key: str, session_id: str) -> None:
        """将连接切换为只绑定当前会话。"""
        async with self._lock:
            client = self._clients.get(client_key)
            if client is not None:
                client.bound_sessions = {session_id}

    async def is_session_bound(self, session_id: str) -> bool:
        """判断是否仍有连接绑定在指定会话上。"""
        async with self._lock:
            for client in self._clients.values():
                if session_id in client.bound_sessions:
                    return True
        return False

    async def broadcast_to_session(self, session_id: str, payload: dict[str, Any]) -> None:
        """向绑定了指定会话的客户端广播事件。"""
        targets: list[RemoteClient] = []
        async with self._lock:
            for client in self._clients.values():
                if session_id in client.bound_sessions:
                    targets.append(client)
        for client in targets:
            try:
                await client.send_json(payload)
            except Exception:
                continue
