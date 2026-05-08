"""Skill 配置模型测试。"""

from __future__ import annotations

from nomi.config.paths import DEFAULT_EXTERNAL_SKILL_ROOTS
from nomi.config.schema import Config


def test_skills_config_uses_default_external_roots() -> None:
    config = Config()

    assert config.skills.external_roots == list(DEFAULT_EXTERNAL_SKILL_ROOTS)


def test_skills_config_accepts_external_roots_camel_case() -> None:
    config = Config.model_validate(
        {
            "skills": {
                "externalRoots": [
                    "~/.claude/skills",
                    "~/.codex/skills",
                    "~/custom-skills",
                ]
            }
        }
    )

    assert config.skills.external_roots == [
        "~/.claude/skills",
        "~/.codex/skills",
        "~/custom-skills",
    ]
