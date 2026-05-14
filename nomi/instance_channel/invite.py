"""实例邀请码编解码。"""

from __future__ import annotations

from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

INVITE_SCHEME = "nomi"
INVITE_HOST = "instance-invite"
INVITE_VERSION = "1"


def build_invite_code(*, key: str, url: str, invite_id: str, secret: str) -> str:
    """构造一次性 instance 邀请码。"""
    query = urlencode(
        {
            "v": INVITE_VERSION,
            "key": str(key or "").strip(),
            "url": str(url or "").strip().rstrip("/"),
            "invite_id": str(invite_id or "").strip(),
            "secret": str(secret or "").strip(),
        },
        quote_via=quote,
    )
    return f"{INVITE_SCHEME}://{INVITE_HOST}?{query}"


def parse_invite_code(code: str) -> dict[str, str]:
    """解析一次性 instance 邀请码。"""
    parsed = urlparse(str(code or "").strip())
    if parsed.scheme != INVITE_SCHEME or parsed.netloc != INVITE_HOST:
        raise ValueError("invalid instance invite code")
    query = parse_qs(parsed.query)
    version = _one(query, "v") or INVITE_VERSION
    key = _one(query, "key")
    url = _one(query, "url").rstrip("/")
    invite_id = _one(query, "invite_id")
    secret = _one(query, "secret")
    if version != INVITE_VERSION:
        raise ValueError("unsupported instance invite version")
    if not key or not url or not invite_id or not secret:
        raise ValueError("invite code must include key, url, invite_id and secret")
    return {"v": version, "key": key, "url": url, "invite_id": invite_id, "secret": secret}


def _one(query: dict[str, list[str]], key: str) -> str:
    """读取 query 中的单值字段。"""
    values = query.get(key) or []
    if not values:
        return ""
    return unquote(str(values[0] or "")).strip()
