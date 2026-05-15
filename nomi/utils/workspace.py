"""工作区模板与初始化相关工具。"""

from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

_SOUL_IDENTITY_PATTERN = re.compile(r"^我是 .+，\s*一个个人 AI 助手。$", re.MULTILINE)


def sync_workspace_templates(workspace: Path, silent: bool = False) -> list[str]:
    """把内置模板同步到工作区。

    参数:
        workspace: 工作区根目录。
        silent: 是否静默跳过终端输出。

    返回:
        本次新增的相对路径列表。
    """
    from importlib.resources import files as pkg_files

    try:
        tpl = pkg_files("nomi") / "templates" / "workspace"
    except Exception:
        return []
    if not tpl.is_dir():
        return []

    added: list[str] = []

    def _write(src, dest: Path) -> None:
        if dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8") if src else "", encoding="utf-8")
        added.append(str(dest.relative_to(workspace)))

    for item in tpl.iterdir():
        if item.name.endswith(".md") and not item.name.startswith("."):
            _write(item, workspace / item.name)
    _write(tpl / "memory" / "MEMORY.md", workspace / "memory" / "MEMORY.md")
    _write(None, workspace / "memory" / "history.jsonl")

    if added and not silent:
        from rich.console import Console

        for name in added:
            Console().print(f"  [dim]已创建 {name}[/dim]")

    try:
        from nomi.utils.gitstore import GitStore

        git_store = GitStore(
            workspace,
            tracked_files=["SOUL.md", "USER.md", "memory/MEMORY.md"],
        )
        git_store.init()
    except Exception:
        logger.warning("Failed to initialize git store for {}", workspace)

    return added


def sync_instance_name_to_soul(workspace: Path, name: str) -> Path:
    """把当前实例名字同步到工作区 `SOUL.md`。

    参数:
        workspace: 工作区根目录。
        name: 已校验或待校验的实例名字。

    返回:
        被写入的 `SOUL.md` 路径。
    """
    from nomi.config.schema.instance import InstanceIdentityConfig

    normalized_name = InstanceIdentityConfig(key=name).key
    workspace_path = Path(workspace).expanduser()
    soul_path = workspace_path / "SOUL.md"
    if not soul_path.exists():
        sync_workspace_templates(workspace_path, silent=True)
    if soul_path.exists():
        content = soul_path.read_text(encoding="utf-8")
    else:
        content = "# 灵魂\n\n我是 nomi，一个个人 AI 助手。\n"

    identity_line = f"我是 {normalized_name}，一个个人 AI 助手。"
    if _SOUL_IDENTITY_PATTERN.search(content):
        updated = _SOUL_IDENTITY_PATTERN.sub(identity_line, content, count=1)
    else:
        updated = _insert_soul_identity_line(content, identity_line)
    soul_path.parent.mkdir(parents=True, exist_ok=True)
    soul_path.write_text(updated, encoding="utf-8")
    return soul_path


def _insert_soul_identity_line(content: str, identity_line: str) -> str:
    """在未知 SOUL 结构中尽量保留用户内容并插入身份行。"""
    lines = content.splitlines()
    if lines and lines[0].strip() == "# 灵魂":
        rest = lines[1:]
        if rest and rest[0].strip() == "":
            return "\n".join([lines[0], "", identity_line, *rest[1:]]) + "\n"
        return "\n".join([lines[0], "", identity_line, *rest]) + "\n"
    stripped = content.rstrip()
    if not stripped:
        return f"# 灵魂\n\n{identity_line}\n"
    return f"{identity_line}\n\n{stripped}\n"
