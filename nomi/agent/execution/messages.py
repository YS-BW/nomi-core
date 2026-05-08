"""执行链路消息结构辅助。"""

from __future__ import annotations

from typing import Any


def build_assistant_message(
    content: str | None,
    tool_calls: list[dict[str, Any]] | None = None,
    reasoning_content: str | None = None,
    reasoning_items: list[dict[str, Any]] | None = None,
    thinking_blocks: list[dict] | None = None,
) -> dict[str, Any]:
    """构造兼容各 provider 的 assistant 消息。"""
    message: dict[str, Any] = {"role": "assistant", "content": content or ""}
    if tool_calls:
        message["tool_calls"] = tool_calls
    if reasoning_content is not None or thinking_blocks:
        message["reasoning_content"] = reasoning_content if reasoning_content is not None else ""
    if reasoning_items:
        message["reasoning_items"] = reasoning_items
    if thinking_blocks:
        message["thinking_blocks"] = thinking_blocks
    return message


def find_legal_message_start(messages: list[dict[str, Any]]) -> int:
    """找到合法消息片段的起始下标。"""
    declared: set[str] = set()
    start = 0
    for index, message in enumerate(messages):
        role = message.get("role")
        if role == "assistant":
            for tool_call in message.get("tool_calls") or []:
                if isinstance(tool_call, dict) and tool_call.get("id"):
                    declared.add(str(tool_call["id"]))
        elif role == "tool":
            tool_call_id = message.get("tool_call_id")
            if tool_call_id and str(tool_call_id) not in declared:
                start = index + 1
                declared.clear()
                for previous in messages[start : index + 1]:
                    if previous.get("role") == "assistant":
                        for tool_call in previous.get("tool_calls") or []:
                            if isinstance(tool_call, dict) and tool_call.get("id"):
                                declared.add(str(tool_call["id"]))
    return start
