"""DeepSeek provider regression tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nomi.providers.backends.deepseek import DeepSeekProvider
from nomi.providers.factory.registry import find_by_name


def _fake_tool_call_response(*, reasoning_content: str | None = "reason", content: str = ""):
    function = SimpleNamespace(name="read_file", arguments='{"path":"README.md"}')
    tool_call = SimpleNamespace(id="call_raw_123", index=0, type="function", function=function)
    message = SimpleNamespace(
        content=content,
        tool_calls=[tool_call],
        reasoning_content=reasoning_content,
    )
    choice = SimpleNamespace(message=message, finish_reason="tool_calls")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


def test_deepseek_sanitize_preserves_empty_content_for_tool_call_messages() -> None:
    spec = find_by_name("deepseek")
    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI"):
        provider = DeepSeekProvider(api_key="sk-test", spec=spec, default_model="deepseek-v4-flash")

    sanitized = provider._sanitize_messages([
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_raw_123",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
            "reasoning_content": "chain",
        },
        {
            "role": "tool",
            "tool_call_id": "call_raw_123",
            "name": "read_file",
            "content": "ok",
        },
    ])

    assert sanitized[1]["content"] == ""
    assert sanitized[1]["reasoning_content"] == "chain"
    assert sanitized[1]["tool_calls"][0]["id"] != "call_raw_123"


def test_deepseek_reasoner_request_strips_reasoning_content() -> None:
    spec = find_by_name("deepseek")
    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI"):
        provider = DeepSeekProvider(api_key="sk-test", spec=spec, default_model="deepseek-reasoner")

    provider._active_model_name = "deepseek-reasoner"
    sanitized = provider._sanitize_messages([
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "done",
            "reasoning_content": "hidden chain",
        },
        {"role": "user", "content": "next"},
    ])

    assert "reasoning_content" not in sanitized[1]


@pytest.mark.asyncio
async def test_deepseek_stream_with_tools_uses_non_streaming_chat_path() -> None:
    spec = find_by_name("deepseek")
    mock_create = AsyncMock(return_value=_fake_tool_call_response())

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = mock_create

        provider = DeepSeekProvider(
            api_key="sk-test",
            api_base="https://api.deepseek.com",
            default_model="deepseek-v4-flash",
            spec=spec,
        )
        result = await provider.chat_stream(
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}],
            model="deepseek-v4-flash",
        )

    assert result.has_tool_calls is True
    call_kwargs = mock_create.call_args.kwargs
    assert "stream" not in call_kwargs
    assert call_kwargs["messages"][0]["content"] == "hello"


@pytest.mark.asyncio
async def test_deepseek_reasoner_rejects_tools_with_clear_error() -> None:
    spec = find_by_name("deepseek")
    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI"):
        provider = DeepSeekProvider(api_key="sk-test", spec=spec, default_model="deepseek-reasoner")

    result = await provider.chat(
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}],
        model="deepseek-reasoner",
    )

    assert result.finish_reason == "error"
    assert "暂不支持 Function Calling" in (result.content or "")
