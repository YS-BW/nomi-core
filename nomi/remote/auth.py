"""remote HTTP/SSE 鉴权工具。"""

from __future__ import annotations

from urllib.parse import parse_qs

from aiohttp import web


def is_authorized_request(
    request: web.Request,
    *,
    expected_token: str,
    allow_query_token: bool = False,
) -> bool:
    """校验 remote Bearer token。"""
    expected = str(expected_token or "").strip()
    auth = str(request.headers.get("Authorization", "") or "").strip()
    if expected and auth == f"Bearer {expected}":
        return True
    if not allow_query_token:
        return False
    query_token = (parse_qs(request.query_string).get("token") or [""])[0].strip()
    return bool(expected and query_token and query_token == expected)
