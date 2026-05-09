"""Qwen provider regression tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nomi.providers.backends.qwen import QwenProvider
from nomi.providers.factory.registry import find_by_name


def _fake_chat_response(content: str = "ok") -> SimpleNamespace:
    message = SimpleNamespace(
        content=content,
        tool_calls=None,
        reasoning_content=None,
    )
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[choice], usage=usage)


def _fake_tool_call_response(*, reasoning_content: str | None = "chain", content: str = "") -> SimpleNamespace:
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


def _fake_chat_stream(text: str = "ok"):
    async def _stream():
        yield SimpleNamespace(
            choices=[SimpleNamespace(finish_reason=None, delta=SimpleNamespace(content=text, reasoning_content=None, tool_calls=None))],
            usage=None,
        )
        yield SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", delta=SimpleNamespace(content=None, reasoning_content=None, tool_calls=None))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    return _stream()


@pytest.mark.asyncio
async def test_qwen_enables_thinking_for_reasoning_mode() -> None:
    mock_create = AsyncMock(return_value=_fake_chat_response("hello"))
    spec = find_by_name("qwen")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = mock_create

        provider = QwenProvider(
            api_key="dashscope-test-key",
            api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
            default_model="qwen-max",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "你好"}],
            model="qwen-max",
            reasoning_effort="high",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["extra_body"]["enable_thinking"] is True


@pytest.mark.asyncio
async def test_qwen_disables_thinking_for_minimal_mode() -> None:
    mock_create = AsyncMock(return_value=_fake_chat_response("hello"))
    spec = find_by_name("qwen")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = mock_create

        provider = QwenProvider(
            api_key="dashscope-test-key",
            api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
            default_model="qwen-max",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "你好"}],
            model="qwen-max",
            reasoning_effort="minimal",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["extra_body"]["enable_thinking"] is False


@pytest.mark.asyncio
async def test_qwen_preserves_thinking_when_history_has_reasoning_content() -> None:
    mock_create = AsyncMock(return_value=_fake_chat_response("hello"))
    spec = find_by_name("qwen")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = mock_create

        provider = QwenProvider(
            api_key="dashscope-test-key",
            api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
            default_model="qwen-max",
            spec=spec,
        )
        await provider.chat(
            messages=[
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "done", "reasoning_content": "hidden chain"},
                {"role": "user", "content": "next"},
            ],
            model="qwen-max",
            reasoning_effort="medium",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["extra_body"]["enable_thinking"] is True
    assert kwargs["extra_body"]["preserve_thinking"] is True


@pytest.mark.asyncio
async def test_qwen_forced_tool_choice_disables_thinking() -> None:
    mock_create = AsyncMock(return_value=_fake_tool_call_response())
    spec = find_by_name("qwen")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = mock_create

        provider = QwenProvider(
            api_key="dashscope-test-key",
            api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
            default_model="qwen-max",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}],
            model="qwen-max",
            reasoning_effort="high",
            tool_choice="required",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["extra_body"]["enable_thinking"] is False
    assert kwargs["tool_choice"] == "required"


@pytest.mark.asyncio
async def test_qwen_chat_stream_keeps_openai_stream_path() -> None:
    spec = find_by_name("qwen")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = AsyncMock(return_value=_fake_chat_stream("hello"))

        provider = QwenProvider(
            api_key="dashscope-test-key",
            api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
            default_model="qwen-max",
            spec=spec,
        )
        deltas: list[str] = []

        async def _on_delta(text: str) -> None:
            deltas.append(text)

        result = await provider.chat_stream(
            messages=[{"role": "user", "content": "你好"}],
            model="qwen-max",
            on_content_delta=_on_delta,
        )

    assert result.content == "hello"
    assert deltas == ["hello"]
    assert client_instance.chat.completions.create.await_count == 1


def test_qwen_never_uses_responses_api() -> None:
    spec = find_by_name("qwen")
    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI"):
        provider = QwenProvider(api_key="dashscope-test-key", spec=spec, default_model="qwen-max")

    assert provider._should_use_responses_api("qwen-max", "high") is False
