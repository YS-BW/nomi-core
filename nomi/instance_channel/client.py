"""实例通道 HTTP client。"""

from __future__ import annotations

import httpx


class InstanceChannelClient:
    """调用另一个 instance 的内部通道接口。"""

    def __init__(self, *, timeout: float = 60.0) -> None:
        """初始化 HTTP client 配置。"""
        self._timeout = timeout

    async def send_relation_request(
        self,
        *,
        url: str,
        invite_id: str,
        secret: str,
        payload: dict,
    ) -> dict:
        """发送关系申请。"""
        return await self._post(
            url,
            "/v1/instance/relations/request",
            payload,
            headers={
                "X-Nomi-Invite-Id": str(invite_id or "").strip(),
                "Authorization": f"Bearer {str(secret or '').strip()}",
            },
        )

    async def send_relation_response(self, request, payload: dict) -> dict:
        """向申请方发送关系确认结果。"""
        return await self._post(
            request.url,
            "/v1/instance/relations/response",
            payload,
            headers={"Authorization": f"Bearer {request.response_token}"},
        )

    async def send_relation_remove(self, relation, payload: dict) -> dict:
        """向关系方发送删除通知。"""
        return await self._post(
            relation.url,
            "/v1/instance/relations/response",
            payload,
            headers={
                "X-Nomi-Relation-Id": relation.relation_id,
                "Authorization": f"Bearer {relation.relation_token}",
            },
        )

    async def send_message(self, relation, payload: dict) -> dict:
        """发送实例消息并等待对方回复。"""
        return await self._post(
            relation.url,
            "/v1/instance/messages",
            payload,
            headers={
                "X-Nomi-Relation-Id": relation.relation_id,
                "Authorization": f"Bearer {relation.relation_token}",
            },
        )

    async def _post(
        self,
        base_url: str,
        path: str,
        payload: dict,
        *,
        headers: dict[str, str],
    ) -> dict:
        """执行 POST 请求。"""
        url = f"{str(base_url or '').rstrip('/')}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
        if response.status_code >= 400:
            raise RuntimeError(f"instance request failed: {response.status_code} {response.text}")
        data = response.json()
        return data if isinstance(data, dict) else {}
