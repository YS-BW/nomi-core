"""默认工具注册。"""

from __future__ import annotations

from pathlib import Path

from nomi.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nomi.agent.tools.image_analysis import AnalyzeImageTool
from nomi.agent.tools.registry import ToolRegistry
from nomi.agent.tools.search import GlobTool, GrepTool
from nomi.agent.tools.shell import ExecTool
from nomi.agent.tools.skill_tools import InstallSkillTool, ListSkillsTool, UninstallSkillTool
from nomi.agent.tools.tasks import (
    TaskCreateAfterTool,
    TaskCreateAtTool,
    TaskCreateDailyTool,
    TaskCreateEveryTool,
    TaskDeleteTool,
    TaskDisableTool,
    TaskEnableTool,
    TaskGetTool,
    TaskListTool,
    TaskRescheduleAfterTool,
    TaskRescheduleAtTool,
    TaskRescheduleDailyTool,
    TaskRescheduleEveryTool,
    TaskUpdateInstructionTool,
)
from nomi.agent.tools.web import WebFetchTool, WebSearchTool
from nomi.config.schema import ExecToolConfig, WebToolsConfig
from nomi.providers.base import LLMProvider
from nomi.session.manager import SessionManager
from nomi.tasks import TaskRunner


def register_default_tools(
    registry: ToolRegistry,
    workspace: Path,
    exec_config: ExecToolConfig,
    web_config: WebToolsConfig,
    restrict_to_workspace: bool,
    task_runner: TaskRunner,
    provider: LLMProvider,
    model: str,
    default_timezone: str,
    extra_allowed_dirs: list[Path],
    sessions: SessionManager,
) -> None:
    """注册主链路默认工具集合。

    参数:
        registry: 当前工具注册表。
        workspace: 当前工作区目录。
        exec_config: Shell 工具配置。
        web_config: Web 工具配置。
        restrict_to_workspace: 是否限制工具访问范围到工作区。
        task_runner: 自动任务 owner。
        default_timezone: 默认时区。
        extra_allowed_dirs: 额外允许访问的目录。
        sessions: 当前会话持久化 owner。

    返回:
        无返回值。
    """
    allowed_dir = workspace if (restrict_to_workspace or exec_config.sandbox) else None
    registry.register(
        ReadFileTool(
            workspace=workspace,
            allowed_dir=allowed_dir,
            extra_allowed_dirs=extra_allowed_dirs,
        )
    )
    for tool_class in (WriteFileTool, EditFileTool, ListDirTool):
        registry.register(tool_class(workspace=workspace, allowed_dir=allowed_dir))
    for tool_class in (GlobTool, GrepTool):
        registry.register(
            tool_class(
                workspace=workspace,
                allowed_dir=allowed_dir,
                extra_allowed_dirs=extra_allowed_dirs,
            )
        )
    registry.register(
        AnalyzeImageTool(
            provider=provider,
            model=model,
            workspace=workspace,
            allowed_dir=allowed_dir,
            extra_allowed_dirs=extra_allowed_dirs,
        )
    )
    for tool_class in (
        TaskCreateAfterTool,
        TaskCreateAtTool,
        TaskCreateDailyTool,
        TaskCreateEveryTool,
        TaskListTool,
        TaskGetTool,
        TaskDeleteTool,
        TaskEnableTool,
        TaskDisableTool,
        TaskUpdateInstructionTool,
        TaskRescheduleAfterTool,
        TaskRescheduleAtTool,
        TaskRescheduleDailyTool,
        TaskRescheduleEveryTool,
    ):
        registry.register(tool_class(task_runner=task_runner, default_timezone=default_timezone))
    if exec_config.enable:
        registry.register(
            ExecTool(
                working_dir=str(workspace),
                timeout=exec_config.timeout,
                restrict_to_workspace=restrict_to_workspace,
                sandbox=exec_config.sandbox,
                path_append=exec_config.path_append,
                allowed_env_keys=exec_config.allowed_env_keys,
                extra_allowed_dirs=extra_allowed_dirs,
            )
        )
    if web_config.enable:
        registry.register(
            WebSearchTool(config=web_config.search, proxy=web_config.proxy)
        )
        registry.register(WebFetchTool(proxy=web_config.proxy))
    registry.register(ListSkillsTool())
    registry.register(InstallSkillTool())
    registry.register(UninstallSkillTool())
