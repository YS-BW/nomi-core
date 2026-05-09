"""Moonshot/Kimi provider regression tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nomi.providers.backends.moonshot import MoonshotProvider
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
async def test_moonshot_enables_thinking_for_optional_reasoning_models() -> None:
    mock_create = AsyncMock(return_value=_fake_chat_response("hello"))
    spec = find_by_name("moonshot")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = mock_create

        provider = MoonshotProvider(
            api_key="moonshot-test-key",
            api_base="https://api.moonshot.cn/v1",
            default_model="kimi-k2.6",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "你好"}],
            model="kimi-k2.6",
            reasoning_effort="high",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["extra_body"]["thinking"] == {"type": "enabled"}


@pytest.mark.asyncio
async def test_moonshot_disables_thinking_for_minimal_optional_models() -> None:
    mock_create = AsyncMock(return_value=_fake_chat_response("hello"))
    spec = find_by_name("moonshot")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = mock_create

        provider = MoonshotProvider(
            api_key="moonshot-test-key",
            api_base="https://api.moonshot.cn/v1",
            default_model="kimi-k2.6",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "你好"}],
            model="kimi-k2.6",
            reasoning_effort="minimal",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["extra_body"]["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
async def test_moonshot_preserves_thinking_history_for_optional_models() -> None:
    mock_create = AsyncMock(return_value=_fake_chat_response("hello"))
    spec = find_by_name("moonshot")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = mock_create

        provider = MoonshotProvider(
            api_key="moonshot-test-key",
            api_base="https://api.moonshot.cn/v1",
            default_model="kimi-k2.6",
            spec=spec,
        )
        await provider.chat(
            messages=[
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "done", "reasoning_content": "hidden chain"},
                {"role": "user", "content": "next"},
            ],
            model="kimi-k2.6",
            reasoning_effort="medium",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["extra_body"]["thinking"] == {"type": "enabled", "keep": "all"}


@pytest.mark.asyncio
async def test_moonshot_dedicated_thinking_model_never_forces_disabled_mode() -> None:
    mock_create = AsyncMock(return_value=_fake_chat_response("hello"))
    spec = find_by_name("moonshot")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = mock_create

        provider = MoonshotProvider(
            api_key="moonshot-test-key",
            api_base="https://api.moonshot.cn/v1",
            default_model="kimi-k2-thinking",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="kimi-k2-thinking",
            reasoning_effort="minimal",
        )

    kwargs = mock_create.call_args.kwargs
    assert "extra_body" not in kwargs or "thinking" not in kwargs["extra_body"]


@pytest.mark.asyncio
async def test_moonshot_forced_tool_choice_downgrades_to_auto() -> None:
    mock_create = AsyncMock(return_value=_fake_tool_call_response())
    spec = find_by_name("moonshot")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = mock_create

        provider = MoonshotProvider(
            api_key="moonshot-test-key",
            api_base="https://api.moonshot.cn/v1",
            default_model="kimi-k2.6",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}],
            model="kimi-k2.6",
            reasoning_effort="high",
            tool_choice="required",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["tool_choice"] == "auto"
    assert kwargs["extra_body"]["thinking"] == {"type": "enabled"}


@pytest.mark.asyncio
async def test_moonshot_chat_stream_keeps_openai_stream_path() -> None:
    spec = find_by_name("moonshot")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = AsyncMock(return_value=_fake_chat_stream("hello"))

        provider = MoonshotProvider(
            api_key="moonshot-test-key",
            api_base="https://api.moonshot.cn/v1",
            default_model="kimi-k2.6",
            spec=spec,
        )
        deltas: list[str] = []

        async def _on_delta(text: str) -> None:
            deltas.append(text)

        result = await provider.chat_stream(
            messages=[{"role": "user", "content": "你好"}],
            model="kimi-k2.6",
            on_content_delta=_on_delta,
        )

    assert result.content == "hello"
    assert deltas == ["hello"]
    assert client_instance.chat.completions.create.await_count == 1


def test_moonshot_never_uses_responses_api() -> None:
    spec = find_by_name("moonshot")
    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI"):
        provider = MoonshotProvider(api_key="moonshot-test-key", spec=spec, default_model="kimi-k2.6")

    assert provider._should_use_responses_api("kimi-k2.6", "high") is False
