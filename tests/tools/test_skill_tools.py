from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from nomi.agent.skills import SkillManager, SkillRegistry
from nomi.agent.tools.bootstrap import register_default_tools
from nomi.agent.tools.registry import ToolRegistry
from nomi.agent.tools.skill_tools import (
    CreateSkillTool,
    FindSkillsTool,
    InstallSkillTool,
    ListSkillsTool,
    UninstallSkillTool,
)
from nomi.config.schema import ExecToolConfig, WebToolsConfig
from nomi.session.manager import SessionManager


def _write_skill(root, key: str, content: str) -> None:
    skill_dir = root / key
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


@pytest.mark.asyncio
async def test_list_skills_tool_returns_installed_items(tmp_path) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root,
        "demo",
        "---\nname: Demo\ndescription: 测试 skill\n---\n",
    )

    tool = ListSkillsTool(
        manager=SkillManager(skills_root),
        registry=SkillRegistry(skills_root),
    )

    result = await tool.execute()

    assert "当前已安装的 skills" in result
    assert "`demo` Demo" in result


@pytest.mark.asyncio
async def test_list_skills_tool_does_not_auto_import_external_skill(tmp_path) -> None:
    skills_root = tmp_path / "skills"
    external_root = tmp_path / ".codex" / "skills"
    _write_skill(
        external_root,
        "demo",
        "---\nname: Demo\ndescription: 外部来源\n---\n",
    )

    tool = ListSkillsTool(
        manager=SkillManager(skills_root, external_roots=[external_root]),
        registry=SkillRegistry(
            skills_root,
            manager=SkillManager(skills_root, external_roots=[external_root]),
        ),
    )

    result = await tool.execute()

    assert result == "当前没有已安装的 skills。"
    assert (skills_root / "demo").exists() is False


@pytest.mark.asyncio
async def test_install_skill_tool_uses_manager_path(tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _write_skill(
        source_root,
        "demo",
        "---\nname: Demo\ndescription: 测试 skill\n---\n",
    )
    skills_root = tmp_path / "skills"
    manager = SkillManager(skills_root)
    monkeypatch.setattr(manager, "_should_link_local_skill", lambda: False)

    tool = InstallSkillTool(
        manager=manager,
        registry=SkillRegistry(skills_root),
    )

    result = await tool.execute(source=str(source_root / "demo"))

    assert "已安装 skill" in result
    assert (skills_root / "demo" / "SKILL.md").exists()


@pytest.mark.asyncio
async def test_find_skills_tool_returns_local_and_external_matches(tmp_path, monkeypatch) -> None:
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root,
        "react-performance",
        "---\nname: React Performance\ndescription: 前端性能\n---\n",
    )
    tool = FindSkillsTool(
        manager=SkillManager(skills_root),
        registry=SkillRegistry(skills_root),
    )

    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=(
                "Install with npx skills add <owner/repo@skill>\n\n"
                "nickcrew/claude-ctx-plugin@react-performance-optimization 1.1K installs\n"
                "└ https://skills.sh/nickcrew/claude-ctx-plugin/react-performance-optimization\n"
            ),
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", _fake_run)
    result = await tool.execute(query="react performance", limit=5)

    assert "本地已安装匹配" in result
    assert "`react-performance` React Performance" in result
    assert "外部候选" in result
    assert "nickcrew/claude-ctx-plugin@react-performance-optimization" in result


@pytest.mark.asyncio
async def test_create_skill_tool_writes_scaffold(tmp_path) -> None:
    tool = CreateSkillTool(
        manager=SkillManager(tmp_path / "skills"),
        registry=SkillRegistry(tmp_path / "skills"),
    )

    result = await tool.execute(skill_key="demo-skill", description="测试创建")

    assert "已创建 skill" in result
    assert (tmp_path / "skills" / "demo-skill" / "SKILL.md").exists()


@pytest.mark.asyncio
async def test_uninstall_skill_tool_wraps_failure_as_error(tmp_path) -> None:
    tool = UninstallSkillTool(
        manager=SkillManager(tmp_path / "skills"),
        registry=SkillRegistry(tmp_path / "skills"),
    )

    result = await tool.execute(skill_key="missing")

    assert result.startswith("Error: ")
    assert "找不到 skill" in result


def test_register_default_tools_includes_skill_management_tools(tmp_path) -> None:
    registry = ToolRegistry()

    register_default_tools(
        registry=registry,
        workspace=tmp_path,
        exec_config=ExecToolConfig(enable=False),
        web_config=WebToolsConfig(enable=False),
        restrict_to_workspace=False,
        task_runner=MagicMock(),
        provider=MagicMock(),
        model="test-model",
        default_timezone="Asia/Shanghai",
        extra_allowed_dirs=[],
        sessions=SessionManager(tmp_path),
    )

    assert "install_skill" in registry.tool_names
    assert "find_skills" in registry.tool_names
    assert "list_skills" in registry.tool_names
    assert "create_skill" in registry.tool_names
    assert "uninstall_skill" in registry.tool_names
    assert "task_create_after" in registry.tool_names
    assert "task_create_at" in registry.tool_names
    assert "task_create_daily" in registry.tool_names
    assert "task_create_every" in registry.tool_names
    assert "task_list" in registry.tool_names
    assert "task_get" in registry.tool_names
    assert "task_delete" in registry.tool_names
    assert "task_enable" in registry.tool_names
    assert "task_disable" in registry.tool_names
    assert "task_update_instruction" in registry.tool_names
    assert "task_reschedule_after" in registry.tool_names
    assert "task_reschedule_at" in registry.tool_names
    assert "task_reschedule_daily" in registry.tool_names
    assert "task_reschedule_every" in registry.tool_names
    assert "analyze_image" in registry.tool_names
    assert "voice_reply_once" not in registry.tool_names
