"""工作区模板初始化测试。"""

from __future__ import annotations

from pathlib import Path

from nomi.utils.workspace import sync_instance_name_to_soul, sync_workspace_templates


def test_sync_workspace_templates_uses_workspace_subdir(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    added = sync_workspace_templates(workspace, silent=True)

    assert "AGENTS.md" in added
    assert "SOUL.md" in added
    assert "USER.md" in added
    assert "memory/MEMORY.md" in added
    assert "memory/history.jsonl" in added
    assert (workspace / "AGENTS.md").is_file()
    assert (workspace / "SOUL.md").is_file()
    assert (workspace / "USER.md").is_file()
    assert not (workspace / "TOOLS.md").exists()
    assert (workspace / "memory" / "MEMORY.md").is_file()
    assert (workspace / "memory" / "history.jsonl").is_file()


def test_sync_instance_name_to_soul_updates_identity_line(tmp_path: Path) -> None:
    """同步实例名字时应只更新 SOUL.md 的自称行。"""
    workspace = tmp_path / "workspace"
    sync_workspace_templates(workspace, silent=True)

    soul_path = sync_instance_name_to_soul(workspace, "小美")

    content = soul_path.read_text(encoding="utf-8")
    assert "我是 小美，一个个人 AI 助手。" in content
    assert "我是 nomi，一个个人 AI 助手。" not in content
