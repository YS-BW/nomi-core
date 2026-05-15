"""OpenAI 兼容 provider 的共享常量与基础辅助。"""

from __future__ import annotations

import html
import re
import secrets
import string
from typing import TYPE_CHECKING, Any

import json_repair

from nomi.providers.base import ToolCallRequest

if TYPE_CHECKING:
    from nomi.providers.factory.registry import ProviderSpec


ALLOWED_MSG_KEYS = frozenset({
    "role", "content", "tool_calls", "tool_call_id", "name",
    "reasoning_content", "reasoning_items", "thinking_blocks", "extra_content",
})
ALNUM = string.ascii_letters + string.digits
STANDARD_TC_KEYS = frozenset({"id", "type", "index", "function"})
STANDARD_FN_KEYS = frozenset({"name", "arguments"})
DEFAULT_OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://github.com/HKUDS/nomi",
    "X-OpenRouter-Title": "nomi",
    "X-OpenRouter-Categories": "cli-agent,personal-agent",
}
PSEUDO_TOOL_CALL_BLOCK_RE = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>",
    re.IGNORECASE | re.DOTALL,
)
PSEUDO_FUNCTION_RE = re.compile(
    r"<function=([A-Za-z0-9_.:-]+)>\s*(.*?)\s*</function>",
    re.IGNORECASE | re.DOTALL,
)
PSEUDO_PARAMETER_RE = re.compile(
    r"<parameter=([A-Za-z0-9_.:-]+)>(.*?)</parameter>",
    re.IGNORECASE | re.DOTALL,
)
DSML_TOOL_CALL_BLOCK_RE = re.compile(
    r"<｜｜DSML｜｜tool_calls>\s*(.*?)\s*</｜｜DSML｜｜tool_calls>",
    re.IGNORECASE | re.DOTALL,
)
DSML_INVOKE_RE = re.compile(
    r"<｜｜DSML｜｜invoke\s+name=[\"']([^\"']+)[\"']\s*>\s*(.*?)\s*</｜｜DSML｜｜invoke>",
    re.IGNORECASE | re.DOTALL,
)
DSML_PARAMETER_RE = re.compile(
    r"<｜｜DSML｜｜parameter\s+name=[\"']([^\"']+)[\"'][^>]*>(.*?)</｜｜DSML｜｜parameter>",
    re.IGNORECASE | re.DOTALL,
)
INT_RE = re.compile(r"^[+-]?\d+$")
FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\d*\.\d+)$")


def short_tool_id() -> str:
    """返回 9 位 provider 安全工具调用 ID。"""
    return "".join(secrets.choice(ALNUM) for _ in range(9))


def get_value(obj: Any, key: str) -> Any:
    """同时兼容 dict 与对象属性读取。"""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def coerce_dict(value: Any) -> dict[str, Any] | None:
    """尝试把值转成 dict。"""
    if value is None:
        return None
    if isinstance(value, dict):
        return value if value else None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict) and dumped:
            return dumped
    return None


def extract_tc_extras(tc: Any) -> tuple[
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
]:
    """提取工具调用附加字段。"""
    extra_content = coerce_dict(get_value(tc, "extra_content"))

    tc_dict = coerce_dict(tc)
    provider_specific_fields = None
    function_provider_specific_fields = None
    if tc_dict is not None:
        leftover = {
            key: value
            for key, value in tc_dict.items()
            if key not in STANDARD_TC_KEYS and key != "extra_content" and value is not None
        }
        if leftover:
            provider_specific_fields = leftover
        fn = coerce_dict(tc_dict.get("function"))
        if fn is not None:
            fn_leftover = {
                key: value
                for key, value in fn.items()
                if key not in STANDARD_FN_KEYS and value is not None
            }
            if fn_leftover:
                function_provider_specific_fields = fn_leftover
    else:
        provider_specific_fields = coerce_dict(get_value(tc, "provider_specific_fields"))
        fn_obj = get_value(tc, "function")
        if fn_obj is not None:
            function_provider_specific_fields = coerce_dict(
                get_value(fn_obj, "provider_specific_fields")
            )

    return extra_content, provider_specific_fields, function_provider_specific_fields


def uses_openrouter_attribution(
    spec: "ProviderSpec | None",
    api_base: str | None,
) -> bool:
    """判断是否需要注入 OpenRouter 归因请求头。"""
    if spec and spec.name == "openrouter":
        return True
    return bool(api_base and "openrouter" in api_base.lower())


def is_direct_openai_base(api_base: str | None) -> bool:
    """判断是否是直连 OpenAI 端点。"""
    if not api_base:
        return True
    normalized = api_base.strip().lower().rstrip("/")
    return "api.openai.com" in normalized and "openrouter" not in normalized


def maybe_mapping(value: Any) -> dict[str, Any] | None:
    """把对象或字典统一成 mapping。"""
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict):
            return dumped
    return None


def get_nested_int(obj: Any, path: tuple[str, ...]) -> int:
    """按路径读取嵌套整数。"""
    current = obj
    for segment in path:
        if current is None:
            return 0
        if isinstance(current, dict):
            current = current.get(segment)
        else:
            current = getattr(current, segment, None)
    return int(current or 0) if current is not None else 0


def extract_text_content(value: Any) -> str | None:
    """从兼容结构里提取文本内容。"""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            item_map = maybe_mapping(item)
            if item_map:
                text = item_map.get("text")
                if isinstance(text, str):
                    parts.append(text)
                    continue
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
                continue
            if isinstance(item, str):
                parts.append(item)
        return "".join(parts) or None
    return str(value)


def extract_usage(response: Any) -> dict[str, int]:
    """提取兼容响应里的 token usage。"""
    usage_obj = None
    response_map = maybe_mapping(response)
    if response_map is not None:
        usage_obj = response_map.get("usage")
    elif hasattr(response, "usage") and response.usage:
        usage_obj = response.usage

    usage_map = maybe_mapping(usage_obj)
    if usage_map is not None:
        result = {
            "prompt_tokens": int(usage_map.get("prompt_tokens") or 0),
            "completion_tokens": int(usage_map.get("completion_tokens") or 0),
            "total_tokens": int(usage_map.get("total_tokens") or 0),
        }
    elif usage_obj:
        result = {
            "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage_obj, "completion_tokens", 0) or 0,
            "total_tokens": getattr(usage_obj, "total_tokens", 0) or 0,
        }
    else:
        return {}

    for path in (
        ("prompt_tokens_details", "cached_tokens"),
        ("cached_tokens",),
        ("prompt_cache_hit_tokens",),
    ):
        cached = get_nested_int(usage_map, path)
        if not cached and usage_obj:
            cached = get_nested_int(usage_obj, path)
        if cached:
            result["cached_tokens"] = cached
            break

    return result


def coerce_pseudo_parameter_value(raw_value: str) -> Any:
    """把伪工具调用里的参数文本尽量转成真实类型。"""
    text = html.unescape(raw_value.strip())
    if text.startswith("<![CDATA[") and text.endswith("]]>"):
        text = text[9:-3]
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    if INT_RE.fullmatch(text):
        try:
            return int(text)
        except ValueError:
            return text
    if FLOAT_RE.fullmatch(text):
        try:
            return float(text)
        except ValueError:
            return text
    if text[:1] in {"{", "[", '"'}:
        try:
            return json_repair.loads(text)
        except Exception:
            return text
    return text


def normalize_tool_arguments(
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """返回工具参数的浅拷贝。"""
    del tool_name
    return dict(arguments)


def extract_pseudo_tool_calls(content: str | None) -> tuple[str | None, list[ToolCallRequest]]:
    """从伪 XML/DSML 工具调用文本里恢复结构化 tool_calls。"""
    if not isinstance(content, str):
        return content, []
    lowered = content.lower()
    if "<tool_call>" not in lowered and "<｜｜dsml｜｜tool_calls>" not in lowered:
        return content, []

    tool_calls: list[ToolCallRequest] = []
    spans: list[tuple[int, int]] = []
    _extract_xml_pseudo_tool_calls(content, tool_calls, spans)
    _extract_dsml_pseudo_tool_calls(content, tool_calls, spans)

    if not tool_calls:
        return content, []

    visible_parts: list[str] = []
    last_end = 0
    for start, end in sorted(spans):
        if start < last_end:
            continue
        visible_parts.append(content[last_end:start])
        last_end = end
    visible_parts.append(content[last_end:])
    visible_content = "".join(visible_parts).strip() or None
    return visible_content, tool_calls


def _extract_xml_pseudo_tool_calls(
    content: str,
    tool_calls: list[ToolCallRequest],
    spans: list[tuple[int, int]],
) -> None:
    """提取旧版 <tool_call> 伪工具调用。"""
    for block in PSEUDO_TOOL_CALL_BLOCK_RE.finditer(content):
        function_match = PSEUDO_FUNCTION_RE.search(block.group(1))
        if function_match is None:
            continue
        _append_pseudo_tool_call(
            tool_calls,
            spans,
            tool_name=function_match.group(1),
            raw_arguments=function_match.group(2),
            parameter_pattern=PSEUDO_PARAMETER_RE,
            span=block.span(),
        )


def _extract_dsml_pseudo_tool_calls(
    content: str,
    tool_calls: list[ToolCallRequest],
    spans: list[tuple[int, int]],
) -> None:
    """提取 DeepSeek DSML 伪工具调用。"""
    for block in DSML_TOOL_CALL_BLOCK_RE.finditer(content):
        for invoke in DSML_INVOKE_RE.finditer(block.group(1)):
            _append_pseudo_tool_call(
                tool_calls,
                spans,
                tool_name=invoke.group(1),
                raw_arguments=invoke.group(2),
                parameter_pattern=DSML_PARAMETER_RE,
                span=block.span(),
            )


def _append_pseudo_tool_call(
    tool_calls: list[ToolCallRequest],
    spans: list[tuple[int, int]],
    *,
    tool_name: str,
    raw_arguments: str,
    parameter_pattern: re.Pattern[str],
    span: tuple[int, int],
) -> None:
    """把一次伪工具调用追加到结果列表。"""
    normalized_name = tool_name.strip()
    if not normalized_name:
        return

    arguments: dict[str, Any] = {}
    for param in parameter_pattern.finditer(raw_arguments):
        key = param.group(1).strip()
        if not key:
            continue
        arguments[key] = coerce_pseudo_parameter_value(param.group(2))

    tool_calls.append(
        ToolCallRequest(
            id=short_tool_id(),
            name=normalized_name,
            arguments=normalize_tool_arguments(normalized_name, arguments),
        )
    )
    spans.append(span)
