"""remote HTTP API 错误映射。"""

from __future__ import annotations

from aiohttp import web

from nomi_protocol.shared import ApiErrorResponse


class RemoteApiError(Exception):
    """描述可直接返回给 HTTP 客户端的 remote API 错误。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = 400,
        details: dict | None = None,
    ) -> None:
        """初始化 API 错误。"""
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


def api_error_response(
    code: str,
    message: str,
    *,
    status: int,
    details: dict | None = None,
) -> web.Response:
    """构造统一 HTTP 错误响应。"""
    payload = ApiErrorResponse(
        error={
            "code": code,
            "message": message,
            "details": details or {},
        }
    )
    return web.json_response(payload.model_dump(mode="json"), status=status)
