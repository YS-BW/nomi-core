"""全局 skill 管理工具。"""

from __future__ import annotations

import re
import subprocess
from typing import Any

from nomi.agent.skills.manager import SkillManager
from nomi.agent.skills.registry import SkillRegistry
from nomi.agent.tools.base import Tool, tool_parameters
from nomi.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
SKILLS_RESULT_RE = re.compile(r"^(?P<package>\S+)\s+(?P<installs>[0-9][0-9A-Za-z.+]*\s+installs)$")


class _SkillTool(Tool):
    """skill 管理工具共享基类。"""

    def __init__(
        self,
        *,
        manager: SkillManager | None = None,
        registry: SkillRegistry | None = None,
    ) -> None:
        """初始化 skill 管理工具。

        参数:
            manager: 可选的 skill 管理 owner。
            registry: 可选的 skill 只读注册表。

        返回:
            无返回值。
        """
        self.manager = manager or SkillManager()
        self.registry = registry or SkillRegistry()


@tool_parameters(tool_parameters_schema(required=[]))
class ListSkillsTool(_SkillTool):
    """列出当前已安装 skill。"""

    @property
    def name(self) -> str:
        """返回工具名称。

        返回:
            工具名称字符串。
        """
        return "list_skills"

    @property
    def description(self) -> str:
        """返回工具用途说明。

        返回:
            面向模型的工具描述文本。
        """
        return "List all installed global skills available under ~/.nomi/skills."

    @property
    def read_only(self) -> bool:
        """声明该工具只读取状态。

        返回:
            恒为 ``True``。
        """
        return True

    async def execute(self, **kwargs: Any) -> str:
        """返回当前已安装 skill 列表。

        参数:
            **kwargs: 无额外参数。

        返回:
            面向模型和终端的技能列表文本。
        """
        del kwargs
        items = self.registry.list_status()
        if not items:
            return "当前没有已安装的 skills。"

        lines = ["当前已安装的 skills："]
        for item in items:
            display_name = str(item.get("name") or item.get("key") or "")
            description = str(item.get("description") or "暂无描述。")
            lines.append(f"- `{item['key']}` {display_name}：{description}")
        return "\n".join(lines)


@tool_parameters(
    tool_parameters_schema(
        query=StringSchema("要查找的 skill 关键词或任务描述", min_length=1),
        limit=IntegerSchema(
            description="最多返回几个外部候选 skill",
            minimum=1,
            maximum=10,
        ),
        required=["query"],
    )
)
class FindSkillsTool(_SkillTool):
    """发现本地和外部技能生态中的相关 skill。"""

    @property
    def name(self) -> str:
        """返回工具名称。

        返回:
            工具名称字符串。
        """
        return "find_skills"

    @property
    def description(self) -> str:
        """返回工具用途说明。

        返回:
            面向模型的工具描述文本。
        """
        return (
            "Search installed skills and the external skills ecosystem for a query, "
            "and return installable candidates."
        )

    @property
    def read_only(self) -> bool:
        """声明该工具只读取状态。

        返回:
            恒为 ``True``。
        """
        return True

    async def execute(self, *, query: str, limit: int = 5, **kwargs: Any) -> str:
        """查找相关 skill。

        参数:
            query: 搜索关键词。
            limit: 外部候选上限。
            **kwargs: 预留参数。

        返回:
            本地命中和外部候选的文本摘要。
        """
        del kwargs
        query_text = query.strip()
        if not query_text:
            return "Error: query 不能为空。"
        local_items = self._find_local_matches(query_text)
        external_items, external_error = self._find_external_matches(query_text, limit=limit)

        lines: list[str] = [f"skill 搜索：`{query_text}`"]
        if local_items:
            lines.append("")
            lines.append("本地已安装匹配：")
            for item in local_items:
                lines.append(
                    f"- `{item['key']}` {item['name']}：{item['description']}"
                )

        if external_items:
            lines.append("")
            lines.append("外部候选：")
            for item in external_items:
                lines.append(
                    f"- `{item['package']}`：{item['installs']}；{item['url']}"
                )
                lines.append(
                    f"  安装：`install_skill(source=\"{item['package']}\")`"
                )
        elif external_error:
            lines.append("")
            lines.append(f"外部搜索不可用：{external_error}")

        if len(lines) == 1:
            lines.append("")
            lines.append("没有找到匹配的本地或外部 skill。")
        return "\n".join(lines)

    def _find_local_matches(self, query: str) -> list[dict[str, str]]:
        """按关键词筛选本地已安装 skill。"""
        terms = [part for part in re.split(r"\s+", query.lower()) if part]
        matches: list[dict[str, str]] = []
        for item in self.registry.list_status():
            haystack = " ".join(
                [
                    str(item.get("key") or ""),
                    str(item.get("name") or ""),
                    str(item.get("description") or ""),
                ]
            ).lower()
            if all(term in haystack for term in terms):
                matches.append(
                    {
                        "key": str(item.get("key") or ""),
                        "name": str(item.get("name") or item.get("key") or ""),
                        "description": str(item.get("description") or "暂无描述。"),
                    }
                )
        return matches

    def _find_external_matches(
        self,
        query: str,
        *,
        limit: int,
    ) -> tuple[list[dict[str, str]], str | None]:
        """通过 `npx skills find` 搜索外部技能生态。"""
        try:
            completed = subprocess.run(
                ["npx", "-y", "skills", "find", *query.split()],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except FileNotFoundError:
            return [], "当前环境缺少 `npx`。"
        except subprocess.TimeoutExpired:
            return [], "skills CLI 搜索超时。"

        if completed.returncode != 0:
            error_text = (completed.stderr or completed.stdout or "").strip()
            return [], error_text or "skills CLI 搜索失败。"

        cleaned = ANSI_ESCAPE_RE.sub("", completed.stdout or "")
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        results: list[dict[str, str]] = []
        pending: dict[str, str] | None = None
        for line in lines:
            matched = SKILLS_RESULT_RE.match(line)
            if matched:
                pending = {
                    "package": matched.group("package"),
                    "installs": matched.group("installs"),
                    "url": "",
                }
                continue
            if pending and line.startswith("└ "):
                pending["url"] = line[2:].strip()
                results.append(pending)
                pending = None
                if len(results) >= limit:
                    break
        return results, None


@tool_parameters(
    tool_parameters_schema(
        source=StringSchema("Skill 来源：本地目录、下载链接或 Git 链接", min_length=1),
        required=["source"],
    )
)
class InstallSkillTool(_SkillTool):
    """安装一个全局 skill。"""

    @property
    def name(self) -> str:
        """返回工具名称。

        返回:
            工具名称字符串。
        """
        return "install_skill"

    @property
    def description(self) -> str:
        """返回工具用途说明。

        返回:
            面向模型的工具描述文本。
        """
        return (
            "Install a global skill from a local directory, downloadable archive URL, "
            "Git repository URL, or skills package reference like owner/repo@skill."
        )

    @property
    def exclusive(self) -> bool:
        """声明该工具需要独占执行。

        返回:
            恒为 ``True``。
        """
        return True

    async def execute(self, *, source: str, **kwargs: Any) -> str:
        """安装指定来源的 skill。

        参数:
            source: skill 来源。
            **kwargs: 预留的额外参数。

        返回:
            安装结果文本。
        """
        del kwargs
        ok, message = self.manager.install(source)
        if not ok:
            return f"Error: {message}"
        return message


@tool_parameters(
    tool_parameters_schema(
        skill_key=StringSchema("要创建的 skill 目录名，只允许小写字母、数字和连字符", min_length=1),
        description=StringSchema("skill 描述，会写入 frontmatter", min_length=1),
        body=StringSchema("可选的 SKILL.md 正文；留空则生成默认模板", nullable=True),
        required=["skill_key", "description"],
    )
)
class CreateSkillTool(_SkillTool):
    """创建一个新的全局 skill 脚手架。"""

    @property
    def name(self) -> str:
        """返回工具名称。

        返回:
            工具名称字符串。
        """
        return "create_skill"

    @property
    def description(self) -> str:
        """返回工具用途说明。

        返回:
            面向模型的工具描述文本。
        """
        return "Create a new global skill scaffold under ~/.nomi/skills."

    @property
    def exclusive(self) -> bool:
        """声明该工具需要独占执行。

        返回:
            恒为 ``True``。
        """
        return True

    async def execute(
        self,
        *,
        skill_key: str,
        description: str,
        body: str | None = None,
        **kwargs: Any,
    ) -> str:
        """创建 skill 脚手架。

        参数:
            skill_key: skill 目录名。
            description: skill 描述。
            body: 可选正文。
            **kwargs: 预留参数。

        返回:
            创建结果文本。
        """
        del kwargs
        ok, message = self.manager.create(
            skill_key,
            description=description,
            body=body,
        )
        if not ok:
            return f"Error: {message}"
        return message


@tool_parameters(
    tool_parameters_schema(
        skill_key=StringSchema("要卸载的 skill 目录名", min_length=1),
        required=["skill_key"],
    )
)
class UninstallSkillTool(_SkillTool):
    """卸载一个全局 skill。"""

    @property
    def name(self) -> str:
        """返回工具名称。

        返回:
            工具名称字符串。
        """
        return "uninstall_skill"

    @property
    def description(self) -> str:
        """返回工具用途说明。

        返回:
            面向模型的工具描述文本。
        """
        return "Remove an installed global skill from ~/.nomi/skills."

    @property
    def exclusive(self) -> bool:
        """声明该工具需要独占执行。

        返回:
            恒为 ``True``。
        """
        return True

    async def execute(self, *, skill_key: str, **kwargs: Any) -> str:
        """卸载指定 skill。

        参数:
            skill_key: skill 目录名。
            **kwargs: 预留的额外参数。

        返回:
            卸载结果文本。
        """
        del kwargs
        ok, message = self.manager.uninstall(skill_key)
        if not ok:
            return f"Error: {message}"
        return message
