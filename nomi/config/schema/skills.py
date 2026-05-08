"""Skill 相关配置模型。"""

from __future__ import annotations

from pydantic import Field

from nomi.config.paths import DEFAULT_EXTERNAL_SKILL_ROOTS

from .base import Base


class SkillsConfig(Base):
    """Skill 扫描与导入配置。"""

    external_roots: list[str] = Field(default_factory=lambda: list(DEFAULT_EXTERNAL_SKILL_ROOTS))
