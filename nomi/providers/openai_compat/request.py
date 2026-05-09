"""OpenAI 兼容 provider 的请求构造逻辑。"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from nomi.providers.base import LLMProvider
from nomi.providers.openai_compat.common import ALLOWED_MSG_KEYS, is_direct_openai_base
from nomi.providers.openai_responses import convert_messages, convert_tools

if TYPE_CHECKING:
    from nomi.providers.backends.openai_compat import OpenAICompatProvider


def apply_cache_control(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    """为 prompt cache 注入 cache_control 标记。"""
    cache_marker = {"type": "ephemeral"}
    new_messages = list(messages)

    def _mark(msg: dict[str, Any]) -> dict[str, Any]:
        content = msg.get("content")
        if isinstance(content, str):
            return {
                **msg,
                "content": [{"type": "text", "text": content, "cache_control": cache_marker}],
            }
        if isinstance(content, list) and content:
            new_content = list(content)
            new_content[-1] = {**new_content[-1], "cache_control": cache_marker}
            return {**msg, "content": new_content}
        return msg

    if new_messages and new_messages[0].get("role") == "system":
        new_messages[0] = _mark(new_messages[0])
    if len(new_messages) >= 3:
        new_messages[-2] = _mark(new_messages[-2])

    new_tools = tools
    if tools:
        new_tools = list(tools)
        for idx in LLMProvider._tool_cache_marker_indices(new_tools):
            new_tools[idx] = {**new_tools[idx], "cache_control": cache_marker}
    return new_messages, new_tools


def normalize_tool_call_id(tool_call_id: Any) -> Any:
    """把工具调用 ID 规范成 provider 安全格式。"""
    if not isinstance(tool_call_id, str):
        return tool_call_id
    if len(tool_call_id) == 9 and tool_call_id.isalnum():
        return tool_call_id
    return hashlib.sha1(tool_call_id.encode()).hexdigest()[:9]


def supports_temperature(
    model_name: str,
    reasoning_effort: str | None = None,
) -> bool:
    """判断模型是否接受 temperature 参数。"""
    if reasoning_effort and reasoning_effort.lower() != "none":
        return False
    name = model_name.lower()
    return not any(token in name for token in ("gpt-5", "o1", "o3", "o4"))


def sanitize_messages(
    provider: "OpenAICompatProvider",
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """清洗消息并统一 tool_call_id。"""
    sanitized = LLMProvider._sanitize_request_messages(messages, ALLOWED_MSG_KEYS)
    id_map: dict[str, str] = {}

    def map_id(value: Any) -> Any:
        """把同一轮中的原始 tool_call_id 归一化到稳定映射。"""
        if not isinstance(value, str):
            return value
        return id_map.setdefault(value, normalize_tool_call_id(value))

    for clean in sanitized:
        if isinstance(clean.get("tool_calls"), list):
            normalized = []
            for tc in clean["tool_calls"]:
                if not isinstance(tc, dict):
                    normalized.append(tc)
                    continue
                tc_clean = dict(tc)
                tc_clean["id"] = map_id(tc_clean.get("id"))
                normalized.append(tc_clean)
            clean["tool_calls"] = normalized
            if clean.get("role") == "assistant":
                clean["content"] = None
        if "tool_call_id" in clean and clean["tool_call_id"]:
            clean["tool_call_id"] = map_id(clean["tool_call_id"])
    return provider._enforce_role_alternation(sanitized)


def build_kwargs(
    provider: "OpenAICompatProvider",
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    model: str | None,
    max_tokens: int,
    temperature: float,
    reasoning_effort: str | None,
    tool_choice: str | dict[str, Any] | None,
) -> dict[str, Any]:
    """构造 Chat Completions 请求参数。"""
    model_name = model or provider.default_model
    spec = provider._spec

    if spec and spec.supports_prompt_caching:
        model_name = model or provider.default_model
        if any(model_name.lower().startswith(prefix) for prefix in ("anthropic/", "claude")):
            messages, tools = apply_cache_control(messages, tools)

    if spec and spec.strip_model_prefix:
        model_name = model_name.split("/")[-1]

    kwargs: dict[str, Any] = {
        "model": model_name,
        "messages": provider._sanitize_messages(
            provider._sanitize_empty_content(messages),
        ),
    }

    if supports_temperature(model_name, reasoning_effort):
        kwargs["temperature"] = temperature

    if spec and getattr(spec, "supports_max_completion_tokens", False):
        kwargs["max_completion_tokens"] = max(1, max_tokens)
    else:
        kwargs["max_tokens"] = max(1, max_tokens)

    if spec:
        model_lower = model_name.lower()
        for pattern, overrides in spec.model_overrides:
            if pattern in model_lower:
                kwargs.update(overrides)
                break

    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort

    extra_body: dict[str, Any] = {}
    if spec and reasoning_effort is not None:
        thinking_enabled = reasoning_effort.lower() != "minimal"
        if spec.name in (
            "volcengine", "volcengine_coding_plan",
            "byteplus", "byteplus_coding_plan",
        ):
            extra_body.update({
                "thinking": {"type": "enabled" if thinking_enabled else "disabled"}
            })

    if extra_body:
        kwargs.setdefault("extra_body", {}).update(extra_body)

    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice or "auto"

    return kwargs


def should_use_responses_api(
    provider: "OpenAICompatProvider",
    model: str | None,
    reasoning_effort: str | None,
) -> bool:
    """判断当前请求是否应该走 Responses API。"""
    if provider._spec and provider._spec.name != "openai":
        return False
    if not is_direct_openai_base(provider._effective_base):
        return False

    model_name = (model or provider.default_model).lower()
    if reasoning_effort and reasoning_effort.lower() != "none":
        return True
    return any(token in model_name for token in ("gpt-5", "o1", "o3", "o4"))


def should_fallback_from_responses_error(e: Exception) -> bool:
    """判断 Responses API 错误是否可以回退到 Chat Completions。"""
    response = getattr(e, "response", None)
    status_code = getattr(e, "status_code", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    if status_code not in {400, 404, 422}:
        return False

    body = (
        getattr(e, "body", None)
        or getattr(e, "doc", None)
        or getattr(response, "text", None)
    )
    body_text = str(body).lower() if body is not None else ""
    compatibility_markers = (
        "responses",
        "response api",
        "max_output_tokens",
        "instructions",
        "previous_response",
        "unsupported",
        "not supported",
        "unknown parameter",
        "unrecognized request argument",
    )
    return any(marker in body_text for marker in compatibility_markers)


def build_responses_body(
    provider: "OpenAICompatProvider",
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    model: str | None,
    max_tokens: int,
    temperature: float,
    reasoning_effort: str | None,
    tool_choice: str | dict[str, Any] | None,
) -> dict[str, Any]:
    """构造 Responses API 请求体。"""
    model_name = model or provider.default_model
    sanitized_messages = provider._sanitize_messages(
        provider._sanitize_empty_content(messages),
    )
    instructions, input_items = convert_messages(sanitized_messages)

    body: dict[str, Any] = {
        "model": model_name,
        "instructions": instructions or None,
        "input": input_items,
        "max_output_tokens": max(1, max_tokens),
        "store": False,
        "stream": False,
    }

    if supports_temperature(model_name, reasoning_effort):
        body["temperature"] = temperature

    if reasoning_effort and reasoning_effort.lower() != "none":
        body["reasoning"] = {"effort": reasoning_effort}
        body["include"] = ["reasoning.encrypted_content"]

    if tools:
        body["tools"] = convert_tools(tools)
        body["tool_choice"] = tool_choice or "auto"

    return body
