"""实例通道 HTTP client。"""

from __future__ import annotations

import httpx


class InstanceChannelClient:
    """调用另一个 instance 的内部通道接口。"""

    def __init__(self, *, timeout: float = 60.0) -> None:
        """初始化 HTTP client 配置。"""
        self._timeout = timeout

    async def send_relation_request(self, relation, payload: dict) -> dict:
        """发送关系申请。"""
        return await self._post(relation.url, relation.token, "/v1/instance/relations/request", payload)

    async def send_relation_response(self, relation, payload: dict) -> dict:
        """发送关系确认结果。"""
        return await self._post(relation.url, relation.token, "/v1/instance/relations/response", payload)

    async def send_message(self, relation, payload: dict) -> dict:
        """发送实例消息并等待对方回复。"""
        return await self._post(relation.url, relation.token, "/v1/instance/messages", payload)

    async def _post(self, base_url: str, token: str, path: str, payload: dict) -> dict:
        """执行带 Bearer token 的 POST 请求。"""
        url = f"{str(base_url or '').rstrip('/')}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
        if response.status_code >= 400:
            raise RuntimeError(f"instance request failed: {response.status_code} {response.text}")
        data = response.json()
        return data if isinstance(data, dict) else {}
