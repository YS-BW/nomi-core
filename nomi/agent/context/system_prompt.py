"""系统提示词组装。"""

from __future__ import annotations

import platform
from pathlib import Path

from nomi.agent.memory.store import MemoryStore
from nomi.agent.skills.registry import SkillRegistry
from nomi.utils.prompt_templates import render_template


class SystemPromptBuilder:
    """负责组装系统提示词主干。"""

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"]
    _MAX_RECENT_HISTORY = 50

    def __init__(
        self,
        workspace: Path,
        *,
        memory_store: MemoryStore,
        skill_registry: SkillRegistry,
    ) -> None:
        """绑定系统提示词构造依赖。

        参数:
            workspace: 当前工作区目录。
            memory_store: 记忆文件读写入口。
            skill_registry: 全局技能注册表。

        返回:
            无返回值。
        """
        self.workspace = workspace
        self.memory_store = memory_store
        self.skill_registry = skill_registry

    def build(self, *, channel: str | None = None) -> str:
        """组装完整 system prompt。"""
        return render_template(
            "SYSTEM.md",
            identity=self._build_identity(channel=channel),
            bootstrap_files=self._load_bootstrap_files(),
            long_term_memory=self._build_long_term_memory(),
            skills_summary=self.skill_registry.build_prompt_summary(),
            recent_history=self._build_recent_history(),
            strip=True,
        )

    def _build_identity(self, *, channel: str | None = None) -> str:
        """返回身份提示词主体。"""
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = (
            f"{'macOS' if system == 'Darwin' else system} "
            f"{platform.machine()}, Python {platform.python_version()}"
        )
        return render_template(
            "IDENTITY.md",
            workspace_path=workspace_path,
            runtime=runtime,
            platform_policy=self._describe_platform_policy(system),
            channel_context=self._describe_channel_context(channel),
            strip=True,
        )

    @staticmethod
    def _describe_channel_context(channel: str | None) -> str:
        """返回当前入口环境说明。"""
        normalized = str(channel or "").strip().lower()
        if normalized == "cli":
            return render_template("CHANNEL_CLI.md", strip=True)
        if normalized == "weixin":
            return render_template("CHANNEL_WEIXIN.md", strip=True)
        if normalized == "instance":
            return render_template("CHANNEL_INSTANCE.md", strip=True)
        return ""

    @staticmethod
    def _describe_platform_policy(system: str) -> str:
        """返回当前平台规则。"""
        if system == "Windows":
            return (
                "- 你当前运行在 Windows 上。不要假设 `grep`、`sed`、`awk` 这类 GNU 工具一定存在。\n"
                "- 当 Windows 原生命令或文件工具更可靠时，优先使用它们。\n"
                "- 如果终端输出出现乱码，请用启用 UTF-8 的方式重试。"
            )
        return (
            "- 你当前运行在 POSIX 系统上。优先使用 UTF-8 和标准 shell 工具。\n"
            "- 当文件工具比 shell 命令更简单或更可靠时，优先使用文件工具。"
        )

    def _load_bootstrap_files(self) -> str:
        """加载工作区里的启动文件。"""
        parts: list[str] = []
        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                parts.append(f"## {filename}\n\n{file_path.read_text(encoding='utf-8')}")
        return "\n\n".join(parts) if parts else ""

    def _build_long_term_memory(self) -> str:
        """构造长期记忆段落。"""
        memory = self.memory_store.get_memory_context()
        if not memory:
            return ""
        return f"# 长期记忆\n\n{memory}"

    def _build_recent_history(self) -> str:
        """构造最近历史段落。"""
        entries = self.memory_store.read_unprocessed_history(
            since_cursor=self.memory_store.get_last_dream_cursor()
        )
        if not entries:
            return ""
        capped = entries[-self._MAX_RECENT_HISTORY :]
        lines = [f"- [{entry['timestamp']}] {entry['content']}" for entry in capped]
        return "# 最近历史\n\n" + "\n".join(lines)
