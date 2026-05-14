"""实例邀请码编解码。"""

from __future__ import annotations

from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

INVITE_SCHEME = "nomi"
INVITE_HOST = "instance-invite"


def build_invite_code(*, name: str, url: str, token: str) -> str:
    """构造 instance 邀请码。"""
    query = urlencode(
        {
            "name": str(name or "").strip(),
            "url": str(url or "").strip().rstrip("/"),
            "token": str(token or "").strip(),
        },
        quote_via=quote,
    )
    return f"{INVITE_SCHEME}://{INVITE_HOST}?{query}"


def parse_invite_code(code: str) -> dict[str, str]:
    """解析 instance 邀请码。"""
    parsed = urlparse(str(code or "").strip())
    if parsed.scheme != INVITE_SCHEME or parsed.netloc != INVITE_HOST:
        raise ValueError("invalid instance invite code")
    query = parse_qs(parsed.query)
    name = _one(query, "name")
    url = _one(query, "url").rstrip("/")
    token = _one(query, "token")
    if not url or not token:
        raise ValueError("invite code must include url and token")
    return {"name": name, "url": url, "token": token}


def _one(query: dict[str, list[str]], key: str) -> str:
    """读取 query 中的单值字段。"""
    values = query.get(key) or []
    if not values:
        return ""
    return unquote(str(values[0] or "")).strip()
