"""会话管理相关错误。"""

from __future__ import annotations


class SessionError(RuntimeError):
    """会话层结构化错误基类。"""

    code = "session_error"

    def __init__(self, message: str, *, session_id: str | None = None) -> None:
        """初始化会话错误。"""
        super().__init__(message)
        self.session_id = session_id


class SessionNotFoundError(SessionError):
    """目标会话不存在。"""

    code = "session_not_found"


class DuplicateSessionIdError(SessionError):
    """会话标识已存在。"""

    code = "duplicate_session_id"


class InvalidPageTokenError(SessionError):
    """分页游标非法。"""

    code = "invalid_page_token"


class SessionDeleteForbiddenError(SessionError):
    """当前会话不允许删除。"""

    code = "session_delete_forbidden"
