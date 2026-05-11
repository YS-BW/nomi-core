"""nomi 配置模块导出。"""

from nomi.config.instance import (
    DEFAULT_INSTANCE_NAME,
    InstanceContext,
    format_instance_name,
    get_instance_name,
    get_instance_root,
    list_instance_contexts,
    register_instance,
    remove_registered_instance,
    resolve_instance_context,
)
from nomi.config.loader import get_config_path, load_config
from nomi.config.paths import (
    DEFAULT_EXTERNAL_SKILL_ROOTS,
    GLOBAL_SKILLS_DIR,
    get_cli_history_path,
    get_data_dir,
    get_history_dir,
    get_logs_dir,
    get_media_dir,
    get_runtime_subdir,
    get_sessions_dir,
    get_skills_dir,
    get_workspace_path,
    is_default_workspace,
)
from nomi.config.schema import Config, SkillsConfig

__all__ = [
    "Config",
    "SkillsConfig",
    "DEFAULT_INSTANCE_NAME",
    "InstanceContext",
    "format_instance_name",
    "get_instance_name",
    "get_instance_root",
    "load_config",
    "get_config_path",
    "list_instance_contexts",
    "register_instance",
    "remove_registered_instance",
    "resolve_instance_context",
    "DEFAULT_EXTERNAL_SKILL_ROOTS",
    "GLOBAL_SKILLS_DIR",
    "get_data_dir",
    "get_history_dir",
    "get_runtime_subdir",
    "get_media_dir",
    "get_logs_dir",
    "get_sessions_dir",
    "get_skills_dir",
    "get_workspace_path",
    "is_default_workspace",
    "get_cli_history_path",
]
