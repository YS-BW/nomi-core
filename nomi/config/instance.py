"""实例上下文、注册表与实例级路径解析。"""

from __future__ import annotations

import json
import re
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

DEFAULT_INSTANCE_NAME = "default"
DEFAULT_INSTANCE_ROOT = Path.home() / ".nomi"
DEFAULT_NAMED_INSTANCES_ROOT = DEFAULT_INSTANCE_ROOT / "instances"
INSTANCE_REGISTRY_PATH = DEFAULT_INSTANCE_ROOT / "instances.json"
INSTANCE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
INSTANCE_RUNTIME_DIR_NAMES = (
    "workspace",
    "logs",
    "skills",
    "history",
    "media",
    "sessions",
)

_current_instance_root: Path | None = None
_current_instance_name: str | None = None


@dataclass(frozen=True, slots=True)
class InstanceContext:
    """描述一份 CLI / runtime 当前绑定的实例上下文。"""

    name: str | None
    root: Path

    @property
    def config_path(self) -> Path:
        """返回该实例对应的配置文件路径。"""
        return self.root / "config.json"


def format_instance_name(name: str | None) -> str:
    """把实例名格式化成便于展示的文本。"""
    return name or "(unregistered)"


def normalize_instance_name(name: str) -> str:
    """校验并规范化实例名。"""
    normalized = str(name or "").strip().lower()
    if not normalized:
        raise ValueError("instance name cannot be empty")
    if normalized != DEFAULT_INSTANCE_NAME and not INSTANCE_NAME_PATTERN.fullmatch(normalized):
        raise ValueError("instance name must contain only lowercase letters, digits, and hyphens")
    return normalized


def get_default_instance_root() -> Path:
    """返回默认实例 root。"""
    return DEFAULT_INSTANCE_ROOT.expanduser().resolve()


def get_instance_registry_path() -> Path:
    """返回实例注册表路径。"""
    return INSTANCE_REGISTRY_PATH.expanduser().resolve()


def derive_instance_root(name: str) -> Path:
    """按实例名推导默认 root。"""
    normalized = normalize_instance_name(name)
    if normalized == DEFAULT_INSTANCE_NAME:
        return get_default_instance_root()
    return (DEFAULT_NAMED_INSTANCES_ROOT / normalized).expanduser().resolve()


def load_instance_registry() -> dict[str, Path]:
    """读取实例注册表。"""
    path = get_instance_registry_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}

    items: dict[str, Path] = {}
    for key, value in raw.items():
        try:
            name = normalize_instance_name(key)
        except ValueError:
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        items[name] = Path(value).expanduser().resolve()
    return items


def save_instance_registry(items: dict[str, Path]) -> None:
    """写回实例注册表。"""
    path = get_instance_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        normalize_instance_name(name): str(Path(root).expanduser().resolve())
        for name, root in items.items()
        if normalize_instance_name(name) != DEFAULT_INSTANCE_NAME
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def list_instance_contexts() -> list[InstanceContext]:
    """返回默认实例和所有已注册实例。"""
    registry = load_instance_registry()
    contexts = [InstanceContext(name=DEFAULT_INSTANCE_NAME, root=get_default_instance_root())]
    for name in sorted(registry):
        if name == DEFAULT_INSTANCE_NAME:
            continue
        contexts.append(InstanceContext(name=name, root=registry[name]))
    return contexts


def register_instance(name: str, root: str | Path | None = None) -> InstanceContext:
    """注册一条命名实例。"""
    normalized = normalize_instance_name(name)
    resolved_root = Path(root).expanduser().resolve() if root is not None else derive_instance_root(normalized)
    if normalized == DEFAULT_INSTANCE_NAME:
        return InstanceContext(name=DEFAULT_INSTANCE_NAME, root=get_default_instance_root())

    registry = load_instance_registry()
    registry[normalized] = resolved_root
    save_instance_registry(registry)
    return InstanceContext(name=normalized, root=resolved_root)


def remove_registered_instance(name: str) -> InstanceContext:
    """移除一条已注册实例。"""
    normalized = normalize_instance_name(name)
    if normalized == DEFAULT_INSTANCE_NAME:
        raise ValueError("default instance cannot be removed")
    registry = load_instance_registry()
    root = registry.pop(normalized, None)
    if root is None:
        raise ValueError(f"instance not found: {normalized}")
    save_instance_registry(registry)
    return InstanceContext(name=normalized, root=root)


def lookup_instance_context(name: str) -> InstanceContext:
    """按实例名解析实例上下文。"""
    normalized = normalize_instance_name(name)
    if normalized == DEFAULT_INSTANCE_NAME:
        return InstanceContext(name=DEFAULT_INSTANCE_NAME, root=get_default_instance_root())
    registry = load_instance_registry()
    root = registry.get(normalized)
    if root is None:
        raise ValueError(f"instance not found: {normalized}")
    return InstanceContext(name=normalized, root=root)


def infer_instance_name(root: str | Path) -> str | None:
    """按 root 反查实例名。"""
    resolved_root = Path(root).expanduser().resolve()
    if resolved_root == get_default_instance_root():
        return DEFAULT_INSTANCE_NAME
    registry = load_instance_registry()
    for name, registered_root in registry.items():
        if registered_root == resolved_root:
            return name
    return None


def resolve_instance_context(
    *,
    instance: str | None = None,
    instance_root: str | Path | None = None,
    config_path: str | Path | None = None,
) -> InstanceContext:
    """按固定优先级解析实例上下文。"""
    if instance_root:
        resolved_root = Path(instance_root).expanduser().resolve()
        resolved_name = normalize_instance_name(instance) if instance else infer_instance_name(resolved_root)
        return InstanceContext(name=resolved_name, root=resolved_root)
    if instance:
        return lookup_instance_context(instance)
    if config_path:
        resolved_root = Path(config_path).expanduser().resolve().parent
        return InstanceContext(name=infer_instance_name(resolved_root), root=resolved_root)
    return InstanceContext(name=DEFAULT_INSTANCE_NAME, root=get_default_instance_root())


def ensure_instance_layout(root: str | Path) -> Path:
    """确保一份实例 root 下的标准目录结构存在。"""
    resolved_root = Path(root).expanduser().resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    for name in INSTANCE_RUNTIME_DIR_NAMES:
        (resolved_root / name).mkdir(parents=True, exist_ok=True)
    return resolved_root


def remove_instance_root(root: str | Path) -> Path:
    """删除一份实例 root。"""
    resolved_root = Path(root).expanduser().resolve()
    if resolved_root.exists():
        shutil.rmtree(resolved_root)
    return resolved_root


def set_instance_context(context: InstanceContext) -> None:
    """设置当前进程绑定的实例上下文。"""
    global _current_instance_name, _current_instance_root
    _current_instance_name = context.name
    _current_instance_root = context.root.expanduser().resolve()


def set_instance_root(root: str | Path, *, name: str | None = None) -> InstanceContext:
    """直接设置当前实例 root。"""
    context = InstanceContext(
        name=normalize_instance_name(name) if name else infer_instance_name(root),
        root=Path(root).expanduser().resolve(),
    )
    set_instance_context(context)
    return context


def get_instance_root() -> Path:
    """返回当前活动实例 root。"""
    return (_current_instance_root or get_default_instance_root()).expanduser().resolve()


def get_instance_name() -> str | None:
    """返回当前活动实例名。"""
    if _current_instance_name:
        return _current_instance_name
    return infer_instance_name(get_instance_root())


@contextmanager
def instance_context_scope(
    *,
    instance: str | None = None,
    instance_root: str | Path | None = None,
    config_path: str | Path | None = None,
    context: InstanceContext | None = None,
) -> Iterator[InstanceContext]:
    """在一个代码块内临时切换实例上下文。"""
    previous = InstanceContext(name=get_instance_name(), root=get_instance_root())
    target = context or resolve_instance_context(
        instance=instance,
        instance_root=instance_root,
        config_path=config_path,
    )
    set_instance_context(target)
    try:
        yield target
    finally:
        set_instance_context(previous)
