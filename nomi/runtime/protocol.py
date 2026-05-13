"""运行时共享协议小工具。"""

from __future__ import annotations


def default_session_id(channel: str, chat_id: str) -> str:
    """返回默认会话键。"""
    return f"{channel}:{chat_id}"
