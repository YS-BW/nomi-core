"""基于当前配置上下文的运行时路径助手。"""

from __future__ import annotations

from pathlib import Path

from nomi.utils.fs import ensure_dir

NOMI_HOME_DIR = Path.home() / ".nomi"
DEFAULT_WORKSPACE_DIR = NOMI_HOME_DIR / "workspace"
DEFAULT_HISTORY_PATH = NOMI_HOME_DIR / "history" / "cli_history"
GLOBAL_SKILLS_DIR = NOMI_HOME_DIR / "skills"
DEFAULT_EXTERNAL_SKILL_ROOTS = ("~/.claude/skills", "~/.codex/skills")


def get_config_path() -> Path:
    """返回当前实例正在使用的配置文件路径。"""
    from nomi.config.loader import get_config_path as _get_config_path

    return _get_config_path()


def get_data_dir() -> Path:
    """返回当前实例的运行时数据目录。"""
    return ensure_dir(get_config_path().parent)


def get_runtime_subdir(name: str) -> Path:
    """返回当前实例下的命名运行时子目录。"""
    return ensure_dir(get_data_dir() / name)


def get_media_dir(channel: str | None = None) -> Path:
    """返回媒体目录；传入频道名时再细分子目录。"""
    media_dir = get_runtime_subdir("media")
    return ensure_dir(media_dir / channel) if channel else media_dir


def get_logs_dir() -> Path:
    """返回日志目录。"""
    return get_runtime_subdir("logs")


def get_history_dir() -> Path:
    """返回实例级 history 目录。"""
    return get_runtime_subdir("history")


def get_skills_dir() -> Path:
    """返回实例级 skills 目录。"""
    return get_runtime_subdir("skills")


def get_sessions_dir() -> Path:
    """返回实例级 sessions 目录。"""
    return get_runtime_subdir("sessions")


def get_cron_dir(workspace: str | Path | None = None) -> Path:
    """返回 cron 数据目录。"""
    return ensure_dir(get_workspace_path(workspace) / "cron")


def get_cron_store_path(workspace: str | Path | None = None) -> Path:
    """返回 cron 存储文件路径。"""
    return get_cron_dir(workspace) / "jobs.json"


def get_tasks_dir(workspace: str | Path | None = None) -> Path:
    """返回任务数据目录。"""
    return ensure_dir(get_workspace_path(workspace) / "tasks")


def get_task_store_path(workspace: str | Path | None = None) -> Path:
    """返回任务定义存储文件路径。"""
    return get_tasks_dir(workspace) / "tasks.json"


def get_reminder_store_path() -> Path:
    """返回实例级全局提醒存储文件路径。"""
    return get_runtime_subdir("tasks") / "reminders.json"


def get_instance_relations_path() -> Path:
    """返回实例关系存储文件路径。"""
    return get_data_dir() / "instance-relations.json"


def get_skill_usage_log_path() -> Path:
    """返回 skill 使用日志文件路径。"""
    return get_logs_dir() / "skill_usage.jsonl"


def get_workspace_path(workspace: str | None = None) -> Path:
    """解析并确保工作区目录存在。"""
    workspace_path = Path(workspace).expanduser() if workspace else get_runtime_subdir("workspace")
    return ensure_dir(workspace_path)


def is_default_workspace(workspace: str | Path | None) -> bool:
    """判断工作区是否落在默认 `~/.nomi/workspace`。"""
    current_path = Path(workspace).expanduser() if workspace is not None else DEFAULT_WORKSPACE_DIR
    return current_path.resolve(strict=False) == DEFAULT_WORKSPACE_DIR.resolve(strict=False)


def get_cli_history_path() -> Path:
    """返回共享 CLI 历史文件路径。"""
    return get_history_dir() / "cli_history"
