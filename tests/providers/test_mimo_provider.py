"""Tests for MiMoProvider behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nomi.providers.backends.mimo import MiMoProvider
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


def _fake_tool_call_response() -> SimpleNamespace:
    function = SimpleNamespace(
        name="task_create_after",
        arguments='{"instruction":"eat","after_seconds":60}',
        provider_specific_fields={"inner": "value"},
    )
    tool_call = SimpleNamespace(
        id="call_123",
        index=0,
        type="function",
        function=function,
        extra_content={"google": {"thought_signature": "signed-token"}},
    )
    message = SimpleNamespace(content=None, tool_calls=[tool_call], reasoning_content=None)
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
async def test_mimo_always_disables_thinking_for_tool_request() -> None:
    mock_create = AsyncMock(return_value=_fake_tool_call_response())
    spec = find_by_name("mimo")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = mock_create

        provider = MiMoProvider(
            api_key="mimo-test-key",
            api_base="https://api.xiaomimimo.com/v1",
            default_model="mimo-v2.5",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "5分钟后提醒我吃饭"}],
            tools=[{"type": "function", "function": {"name": "task_create_after", "parameters": {"type": "object"}}}],
            model="mimo-v2.5",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["extra_body"]["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
async def test_mimo_plain_chat_also_disables_thinking() -> None:
    mock_create = AsyncMock(return_value=_fake_chat_response("hello"))
    spec = find_by_name("mimo")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = mock_create

        provider = MiMoProvider(
            api_key="mimo-test-key",
            api_base="https://api.xiaomimimo.com/v1",
            default_model="mimo-v2.5",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "你好"}],
            model="mimo-v2.5",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["extra_body"]["thinking"] == {"type": "disabled"}
    assert kwargs["top_p"] == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_mimo_chat_stream_with_tools_keeps_stream_api() -> None:
    spec = find_by_name("mimo")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = AsyncMock(
            return_value=_fake_chat_stream("<tool_call>"),
        )

        provider = MiMoProvider(
            api_key="mimo-test-key",
            api_base="https://api.xiaomimimo.com/v1",
            default_model="mimo-v2.5",
            spec=spec,
        )
        deltas: list[str] = []

        async def _on_delta(text: str) -> None:
            deltas.append(text)

        result = await provider.chat_stream(
            messages=[{"role": "user", "content": "5分钟后提醒我吃饭"}],
            tools=[{"type": "function", "function": {"name": "task_create_after", "parameters": {"type": "object"}}}],
            model="mimo-v2.5",
            on_content_delta=_on_delta,
        )

    assert result.content == "<tool_call>"
    assert deltas == ["<tool_call>"]
    assert client_instance.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_mimo_chat_stream_without_tools_keeps_streaming() -> None:
    spec = find_by_name("mimo")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = AsyncMock(return_value=_fake_chat_stream("hello"))

        provider = MiMoProvider(
            api_key="mimo-test-key",
            api_base="https://api.xiaomimimo.com/v1",
            default_model="mimo-v2.5",
            spec=spec,
        )
        deltas: list[str] = []

        async def _on_delta(text: str) -> None:
            deltas.append(text)

        result = await provider.chat_stream(
            messages=[{"role": "user", "content": "你好"}],
            model="mimo-v2.5",
            on_content_delta=_on_delta,
        )

    assert result.content == "hello"
    assert deltas == ["hello"]


@pytest.mark.asyncio
async def test_mimo_preserves_extra_content_on_tool_calls() -> None:
    mock_create = AsyncMock(return_value=_fake_tool_call_response())
    spec = find_by_name("mimo")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = mock_create

        provider = MiMoProvider(
            api_key="mimo-test-key",
            api_base="https://api.xiaomimimo.com/v1",
            default_model="mimo-v2.5",
            spec=spec,
        )
        result = await provider.chat(
            messages=[{"role": "user", "content": "run exec"}],
            tools=[{"type": "function", "function": {"name": "task_create_after", "parameters": {"type": "object"}}}],
            model="mimo-v2.5",
        )

    assert len(result.tool_calls) == 1
    tool_call = result.tool_calls[0]
    assert tool_call.extra_content == {"google": {"thought_signature": "signed-token"}}
    assert tool_call.function_provider_specific_fields == {"inner": "value"}


@pytest.mark.asyncio
async def test_mimo_logs_raw_chat_response_when_tool_result_is_suspicious() -> None:
    """带工具请求在可疑返回时应记录原始 MiMo 响应。"""
    mock_create = AsyncMock(return_value=_fake_tool_call_response())
    spec = find_by_name("mimo")

    with (
        patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client,
        patch("nomi.providers.backends.mimo.logger.warning") as mock_warning,
    ):
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = mock_create

        provider = MiMoProvider(
            api_key="mimo-test-key",
            api_base="https://api.xiaomimimo.com/v1",
            default_model="mimo-v2.5",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "2分钟后提醒我起床"}],
            tools=[{"type": "function", "function": {"name": "task_create_after", "parameters": {"type": "object"}}}],
            model="mimo-v2.5",
        )

    mock_warning.assert_called_once()
    assert "MiMo raw {} response" in str(mock_warning.call_args)
    assert "'chat'" in str(mock_warning.call_args)


@pytest.mark.asyncio
async def test_mimo_logs_stream_summary_when_tool_stream_is_empty() -> None:
    """带工具流式返回为空时应记录流式摘要。"""
    spec = find_by_name("mimo")

    with (
        patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client,
        patch("nomi.providers.backends.mimo.logger.warning") as mock_warning,
    ):
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = AsyncMock(return_value=_fake_chat_stream(""))

        provider = MiMoProvider(
            api_key="mimo-test-key",
            api_base="https://api.xiaomimimo.com/v1",
            default_model="mimo-v2.5",
            spec=spec,
        )

        result = await provider.chat_stream(
            messages=[{"role": "user", "content": "2分钟后提醒我起床"}],
            tools=[{"type": "function", "function": {"name": "task_create_after", "parameters": {"type": "object"}}}],
            model="mimo-v2.5",
        )

    assert result.content is None
    mock_warning.assert_called_once()
    assert "MiMo raw stream response summary" in str(mock_warning.call_args)
