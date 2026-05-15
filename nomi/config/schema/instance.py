"""Instance identity 配置。"""

from __future__ import annotations

from pydantic import Field, field_validator

from .base import Base


class InstanceIdentityConfig(Base):
    """当前 Nomi instance 的对外身份配置。"""

    key: str = Field(default="nomi", max_length=64)

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        """校验 Nomi 对外名字。"""
        key = str(value or "").strip()
        if not key:
            return "nomi"
        if ":" in key or "/" in key:
            raise ValueError("instance.key cannot contain ':' or '/'")
        if len(key) > 64:
            raise ValueError("instance.key must be at most 64 characters")
        return key
