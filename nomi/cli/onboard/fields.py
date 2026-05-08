"""onboard 向导的字段元信息与格式化辅助。"""

from __future__ import annotations

import json
import types
from functools import lru_cache
from typing import Any, NamedTuple, get_args, get_origin

from pydantic import BaseModel


class FieldTypeInfo(NamedTuple):
    """保存字段类型推断结果。"""

    type_name: str
    inner_type: Any


_SENSITIVE_KEYWORDS = frozenset({"api_key", "token", "secret", "password", "credentials"})


def get_field_type_info(field_info) -> FieldTypeInfo:
    """提取 Pydantic 字段的类型信息。"""
    annotation = field_info.annotation
    if annotation is None:
        return FieldTypeInfo("str", None)

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is types.UnionType:
        non_none_args = [item for item in args if item is not type(None)]
        if len(non_none_args) == 1:
            annotation = non_none_args[0]
            origin = get_origin(annotation)
            args = get_args(annotation)

    simple_types: dict[type, str] = {bool: "bool", int: "int", float: "float"}

    if origin is list or (hasattr(origin, "__name__") and origin.__name__ == "List"):
        return FieldTypeInfo("list", args[0] if args else str)
    if origin is dict or (hasattr(origin, "__name__") and origin.__name__ == "Dict"):
        return FieldTypeInfo("dict", None)
    for py_type, name in simple_types.items():
        if annotation is py_type:
            return FieldTypeInfo(name, None)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return FieldTypeInfo("model", annotation)
    return FieldTypeInfo("str", None)


def get_field_display_name(field_key: str, field_info) -> str:
    """返回字段展示名。"""
    if field_info and field_info.description:
        return field_info.description
    name = field_key
    suffix_map = {
        "_s": " (seconds)",
        "_ms": " (ms)",
        "_url": " URL",
        "_path": " Path",
        "_id": " ID",
        "_key": " Key",
        "_token": " Token",
    }
    for suffix, replacement in suffix_map.items():
        if name.endswith(suffix):
            name = name[: -len(suffix)] + replacement
            break
    return name.replace("_", " ").title()


def is_sensitive_field(field_name: str) -> bool:
    """判断字段名是否表示敏感内容。"""
    return any(keyword in field_name.lower() for keyword in _SENSITIVE_KEYWORDS)


def mask_value(value: str) -> str:
    """遮罩敏感值，只保留末尾 4 位。"""
    if len(value) <= 4:
        return "****"
    return "*" * (len(value) - 4) + value[-4:]


def format_value(value: Any, rich: bool = True, field_name: str = "") -> str:
    """递归格式化字段值，供展示层复用。"""
    if value is None or value == "" or value == {} or value == []:
        return "[dim]not set[/dim]" if rich else "[not set]"
    if is_sensitive_field(field_name) and isinstance(value, str):
        masked = mask_value(value)
        return f"[dim]{masked}[/dim]" if rich else masked
    if isinstance(value, BaseModel):
        parts = []
        for name, _field_info in type(value).model_fields.items():
            field_value = getattr(value, name, None)
            formatted = format_value(field_value, rich=False, field_name=name)
            if formatted != "[not set]":
                parts.append(f"{name}={formatted}")
        return ", ".join(parts) if parts else ("[dim]not set[/dim]" if rich else "[not set]")
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value)
    return str(value)


def format_value_for_input(value: Any, field_type: str) -> str:
    """把字段当前值格式化成输入框默认值。"""
    if value is None or value == "":
        return ""
    if field_type == "list" and isinstance(value, list):
        return ",".join(str(item) for item in value)
    if field_type == "dict" and isinstance(value, dict):
        return json.dumps(value)
    return str(value)


@lru_cache(maxsize=1)
def get_provider_info() -> dict[str, tuple[str, bool, bool, str]]:
    """从 provider 注册表提取展示信息。"""
    from nomi.providers.factory.registry import PROVIDERS

    return {
        spec.name: (
            spec.display_name or spec.name,
            spec.is_gateway,
            spec.is_local,
            spec.default_api_base,
        )
        for spec in PROVIDERS
    }


def get_provider_names() -> dict[str, str]:
    """返回 provider 的 key -> 展示名 映射。"""
    info = get_provider_info()
    return {name: data[0] for name, data in info.items() if name}


def summarize_model(obj: BaseModel) -> list[tuple[str, str]]:
    """递归汇总一个 Pydantic 模型。"""
    items: list[tuple[str, str]] = []
    for field_name, field_info in type(obj).model_fields.items():
        value = getattr(obj, field_name, None)
        if value is None or value == "" or value == {} or value == []:
            continue
        display = get_field_display_name(field_name, field_info)
        field_type = get_field_type_info(field_info)
        if field_type.type_name == "model" and isinstance(value, BaseModel):
            for nested_field, nested_value in summarize_model(value):
                items.append((f"{display}.{nested_field}", nested_value))
            continue
        formatted = format_value(value, rich=False, field_name=field_name)
        if formatted != "[not set]":
            items.append((display, formatted))
    return items
