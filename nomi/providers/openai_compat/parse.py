"""OpenAI 兼容 provider 的响应解析逻辑。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import json_repair

from nomi.providers.base import LLMResponse, ToolCallRequest
from nomi.providers.openai_compat.common import (
    extract_pseudo_tool_calls,
    extract_tc_extras,
    extract_text_content,
    extract_usage,
    get_value,
    maybe_mapping,
    normalize_tool_arguments,
    short_tool_id,
)

if TYPE_CHECKING:
    from nomi.providers.backends.openai_compat import OpenAICompatProvider


def parse_response(provider: "OpenAICompatProvider", response: Any) -> LLMResponse:
    """把单次非流式响应解析成统一结构。"""
    if isinstance(response, str):
        return LLMResponse(content=response, finish_reason="stop")

    response_map = maybe_mapping(response)
    if response_map is not None:
        choices = response_map.get("choices") or []
        if not choices:
            content = extract_text_content(
                response_map.get("content") or response_map.get("output_text")
            )
            reasoning_content = extract_text_content(response_map.get("reasoning_content"))
            if content is not None:
                return LLMResponse(
                    content=content,
                    reasoning_content=reasoning_content,
                    finish_reason=str(response_map.get("finish_reason") or "stop"),
                    usage=extract_usage(response_map),
                )
            return LLMResponse(content="Error: API returned empty choices.", finish_reason="error")

        choice0 = maybe_mapping(choices[0]) or {}
        msg0 = maybe_mapping(choice0.get("message")) or {}
        content = extract_text_content(msg0.get("content"))
        finish_reason = str(choice0.get("finish_reason") or "stop")

        raw_tool_calls: list[Any] = []
        if not content and msg0.get("reasoning"):
            content = extract_text_content(msg0.get("reasoning"))
        reasoning_content = msg0.get("reasoning_content")
        if not reasoning_content and msg0.get("reasoning"):
            reasoning_content = extract_text_content(msg0.get("reasoning"))
        for choice in choices:
            choice_map = maybe_mapping(choice) or {}
            message = maybe_mapping(choice_map.get("message")) or {}
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                raw_tool_calls.extend(tool_calls)
                if choice_map.get("finish_reason") in ("tool_calls", "stop"):
                    finish_reason = str(choice_map["finish_reason"])
            if not content:
                content = extract_text_content(message.get("content"))
            if not reasoning_content:
                reasoning_content = message.get("reasoning_content")

        parsed_tool_calls = _parse_tool_calls(raw_tool_calls)
        if not parsed_tool_calls:
            content, parsed_tool_calls = extract_pseudo_tool_calls(content)

        return LLMResponse(
            content=content,
            tool_calls=parsed_tool_calls,
            finish_reason=finish_reason,
            usage=extract_usage(response_map),
            reasoning_content=reasoning_content if isinstance(reasoning_content, str) else None,
        )

    if not response.choices:
        return LLMResponse(content="Error: API returned empty choices.", finish_reason="error")

    choice = response.choices[0]
    message = choice.message
    content = message.content
    finish_reason = choice.finish_reason

    raw_tool_calls: list[Any] = []
    for item in response.choices:
        msg = item.message
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            raw_tool_calls.extend(msg.tool_calls)
            if item.finish_reason in ("tool_calls", "stop"):
                finish_reason = item.finish_reason
        if not content and msg.content:
            content = msg.content
        if not content and getattr(msg, "reasoning", None):
            content = msg.reasoning

    tool_calls = _parse_tool_calls(raw_tool_calls, sdk_mode=True)
    reasoning_content = getattr(message, "reasoning_content", None) or None
    if not reasoning_content and getattr(message, "reasoning", None):
        reasoning_content = message.reasoning

    if not tool_calls:
        content, tool_calls = extract_pseudo_tool_calls(content)

    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        finish_reason=finish_reason or "stop",
        usage=extract_usage(response),
        reasoning_content=reasoning_content,
    )


def parse_chunks(chunks: list[Any]) -> LLMResponse:
    """把流式 chunks 合并成统一响应。"""
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tc_bufs: dict[int, dict[str, Any]] = {}
    finish_reason = "stop"
    usage: dict[str, int] = {}

    def _accum_tc(tc: Any, idx_hint: int) -> None:
        tc_index: int = get_value(tc, "index") if get_value(tc, "index") is not None else idx_hint
        buf = tc_bufs.setdefault(tc_index, {
            "id": "",
            "name": "",
            "arguments": "",
            "extra_content": None,
            "prov": None,
            "fn_prov": None,
        })
        tc_id = get_value(tc, "id")
        if tc_id:
            buf["id"] = str(tc_id)
        fn = get_value(tc, "function")
        if fn is not None:
            fn_name = get_value(fn, "name")
            if fn_name:
                buf["name"] = str(fn_name)
            fn_args = get_value(fn, "arguments")
            if fn_args:
                buf["arguments"] += str(fn_args)
        extra_content, prov, fn_prov = extract_tc_extras(tc)
        if extra_content:
            buf["extra_content"] = extra_content
        if prov:
            buf["prov"] = prov
        if fn_prov:
            buf["fn_prov"] = fn_prov

    for chunk in chunks:
        if isinstance(chunk, str):
            content_parts.append(chunk)
            continue

        chunk_map = maybe_mapping(chunk)
        if chunk_map is not None:
            choices = chunk_map.get("choices") or []
            if not choices:
                usage = extract_usage(chunk_map) or usage
                text = extract_text_content(
                    chunk_map.get("content") or chunk_map.get("output_text")
                )
                if text:
                    content_parts.append(text)
                continue
            choice = maybe_mapping(choices[0]) or {}
            if choice.get("finish_reason"):
                finish_reason = str(choice["finish_reason"])
            delta = maybe_mapping(choice.get("delta")) or {}
            text = extract_text_content(delta.get("content"))
            if text:
                content_parts.append(text)
            text = extract_text_content(delta.get("reasoning_content"))
            if not text:
                text = extract_text_content(delta.get("reasoning"))
            if text:
                reasoning_parts.append(text)
            for idx, tool_call in enumerate(delta.get("tool_calls") or []):
                _accum_tc(tool_call, idx)
            usage = extract_usage(chunk_map) or usage
            continue

        if not chunk.choices:
            usage = extract_usage(chunk) or usage
            continue
        choice = chunk.choices[0]
        if choice.finish_reason:
            finish_reason = choice.finish_reason
        delta = choice.delta
        if delta and delta.content:
            content_parts.append(delta.content)
        if delta:
            reasoning = getattr(delta, "reasoning_content", None)
            if not reasoning:
                reasoning = getattr(delta, "reasoning", None)
            if reasoning:
                reasoning_parts.append(reasoning)
        for tool_call in (delta.tool_calls or []) if delta else []:
            _accum_tc(tool_call, getattr(tool_call, "index", 0))

    parsed_tool_calls = [
        ToolCallRequest(
            id=buf["id"] or short_tool_id(),
            name=buf["name"],
            arguments=normalize_tool_arguments(
                buf["name"],
                json_repair.loads(buf["arguments"]) if buf["arguments"] else {},
            ),
            extra_content=buf.get("extra_content"),
            provider_specific_fields=buf.get("prov"),
            function_provider_specific_fields=buf.get("fn_prov"),
        )
        for buf in tc_bufs.values()
    ]
    content = "".join(content_parts) or None
    if not parsed_tool_calls:
        content, parsed_tool_calls = extract_pseudo_tool_calls(content)

    return LLMResponse(
        content=content,
        tool_calls=parsed_tool_calls,
        finish_reason=finish_reason,
        usage=usage,
        reasoning_content="".join(reasoning_parts) or None,
    )


def _parse_tool_calls(raw_tool_calls: list[Any], sdk_mode: bool = False) -> list[ToolCallRequest]:
    """把原始工具调用数组解析成统一 ToolCallRequest。"""
    parsed = []
    for tool_call in raw_tool_calls:
        if sdk_mode:
            args = tool_call.function.arguments
            if isinstance(args, str):
                args = json_repair.loads(args)
            extra_content, prov, fn_prov = extract_tc_extras(tool_call)
            parsed.append(
                ToolCallRequest(
                    id=short_tool_id(),
                    name=tool_call.function.name,
                    arguments=normalize_tool_arguments(
                        tool_call.function.name,
                        args if isinstance(args, dict) else {},
                    ),
                    extra_content=extra_content,
                    provider_specific_fields=prov,
                    function_provider_specific_fields=fn_prov,
                )
            )
            continue

        tc_map = maybe_mapping(tool_call) or {}
        fn = maybe_mapping(tc_map.get("function")) or {}
        args = fn.get("arguments", {})
        if isinstance(args, str):
            args = json_repair.loads(args)
        extra_content, prov, fn_prov = extract_tc_extras(tool_call)
        parsed.append(
            ToolCallRequest(
                id=short_tool_id(),
                name=str(fn.get("name") or ""),
                arguments=normalize_tool_arguments(
                    str(fn.get("name") or ""),
                    args if isinstance(args, dict) else {},
                ),
                extra_content=extra_content,
                provider_specific_fields=prov,
                function_provider_specific_fields=fn_prov,
            )
        )
    return parsed
