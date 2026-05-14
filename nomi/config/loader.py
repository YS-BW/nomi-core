"""配置加载与保存。"""

import json
import os
import re
from pathlib import Path

import pydantic

from nomi.config.instance import (
    DEFAULT_INSTANCE_NAME,
    InstanceContext,
    ensure_instance_layout,
    get_instance_name,
    get_instance_root,
    resolve_instance_context,
    set_instance_context,
)
from nomi.config.schema import Config

_REMOVED_TOP_LEVEL_KEYS = ("api", "gateway", "channels")
_current_config_path: Path | None = None


def set_config_path(path: Path) -> None:
    """设置当前配置文件路径。"""
    global _current_config_path
    _current_config_path = path.expanduser().resolve()
    ensure_instance_layout(_current_config_path.parent)
    set_instance_context(
        InstanceContext(
            name=None,
            root=_current_config_path.parent,
        )
    )


def set_instance_root(path: Path, *, name: str | None = None) -> None:
    """设置当前实例 root。"""
    global _current_config_path
    _current_config_path = path.expanduser().resolve() / "config.json"
    ensure_instance_layout(_current_config_path.parent)
    set_instance_context(
        InstanceContext(
            name=name,
            root=_current_config_path.parent,
        )
    )


def get_config_path() -> Path:
    """返回当前配置文件路径。"""
    return get_instance_root() / "config.json"


def configure_instance_context(
    *,
    instance: str | None = None,
    instance_root: str | Path | None = None,
    config_path: str | Path | None = None,
) -> InstanceContext:
    """按优先级解析并激活当前实例上下文。"""
    global _current_config_path
    context = resolve_instance_context(
        instance=instance,
        instance_root=instance_root,
        config_path=config_path,
    )
    ensure_instance_layout(context.root)
    set_instance_context(context)
    _current_config_path = context.config_path
    return context


def load_config(config_path: Path | None = None) -> Config:
    """从 JSON 配置文件加载配置。

    参数:
        config_path: 可选的配置文件路径，未提供时使用当前活动路径。

    返回:
        解析后的配置对象；当文件不存在时返回默认配置。

    异常:
        ValueError: 配置文件内容非法，或仍包含已移除的顶层配置段。
    """
    path = config_path or get_config_path()

    if not path.exists():
        return _apply_instance_defaults(Config())

    try:
        with open(path, encoding="utf-8-sig") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置文件不是合法 JSON: {path}") from exc

    _raise_if_removed_keys_present(data, path)
    data = _migrate_defaults_model_to_provider(data)

    try:
        return _apply_instance_defaults(Config.model_validate(data))
    except pydantic.ValidationError as exc:
        raise ValueError(f"配置文件校验失败: {path}\n{exc}") from exc


def save_config(config: Config, config_path: Path | None = None) -> None:
    """把配置保存为 JSON 文件。"""
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(mode="json", by_alias=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def resolve_config_env_vars(config: Config) -> Config:
    """返回已解析 `${VAR}` 环境变量占位符的新配置对象。"""
    data = config.model_dump(mode="json", by_alias=True)
    data = _resolve_env_vars(data)
    return _apply_instance_defaults(Config.model_validate(data))


def _migrate_defaults_model_to_provider(data: object) -> object:
    """把旧版 `agents.defaults.model` 迁移到 active provider 的 `model`。"""
    if not isinstance(data, dict):
        return data
    agents = data.get("agents")
    if not isinstance(agents, dict):
        return data
    defaults = agents.get("defaults")
    if not isinstance(defaults, dict):
        return data
    model = defaults.pop("model", None)
    if not isinstance(model, str) or not model.strip():
        return data

    provider_name = str(defaults.get("provider") or "mimo").strip() or "mimo"
    providers = data.setdefault("providers", {})
    if not isinstance(providers, dict):
        return data
    provider_config = providers.setdefault(provider_name, {})
    if isinstance(provider_config, dict) and not provider_config.get("model"):
        provider_config["model"] = model
    return data


def _resolve_env_vars(obj: object) -> object:
    """递归解析字符串中的 `${VAR}` 占位符。"""
    if isinstance(obj, str):
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", _env_replace, obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(v) for v in obj]
    return obj


def _env_replace(match: re.Match[str]) -> str:
    """将单个环境变量占位符替换为实际值。"""
    name = match.group(1)
    value = os.environ.get(name)
    if value is None:
        raise ValueError(
            f"Environment variable '{name}' referenced in config is not set"
        )
    return value


def _raise_if_removed_keys_present(data: object, path: Path) -> None:
    """检查配置中是否仍包含已移除的 Frozen 顶层字段。

    参数:
        data: 原始 JSON 解析结果。
        path: 当前配置文件路径。

    返回:
        无返回值。

    异常:
        ValueError: 命中已移除字段时抛出，提示用户手动清理旧配置。
    """
    if not isinstance(data, dict):
        return

    removed_keys = [key for key in _REMOVED_TOP_LEVEL_KEYS if key in data]
    if not removed_keys:
        return

    removed_list = ", ".join(removed_keys)
    if "channels" in removed_keys:
        raise ValueError(
            "配置文件使用了已移除的 `channels` 根结构。"
            "请改用新的 `channel.kind + channel.weixin + channel.feishu` 结构后重试。"
            f"\n配置文件：{path}"
        )
    raise ValueError(
        f"配置文件包含已移除的顶层字段: {removed_list}。"
        f"请从 {path} 删除这些字段后重试。"
    )


def _apply_instance_defaults(config: Config) -> Config:
    """把实例 root 相关默认路径写回配置对象。"""
    instance_root = get_instance_root()
    instance_name = get_instance_name() or DEFAULT_INSTANCE_NAME
    if not str(config.instance.key or "").strip():
        config.instance.key = instance_name
    default_workspace = (Path.home() / ".nomi" / "workspace").resolve(strict=False)
    current_workspace = Path(config.agents.defaults.workspace).expanduser().resolve(strict=False)
    if current_workspace == default_workspace:
        config.agents.defaults.workspace = str(instance_root / "workspace")
    return config
