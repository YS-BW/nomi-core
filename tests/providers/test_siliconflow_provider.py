"""SiliconFlow provider regression tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nomi.providers.backends.siliconflow import SiliconFlowProvider
from nomi.providers.factory.registry import find_by_name


def _fake_chat_response(content: str = "ok") -> SimpleNamespace:
    message = SimpleNamespace(
        content=content,
        tool_calls=None,
        reasoning_content="hidden chain",
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
            choices=[SimpleNamespace(finish_reason=None, delta=SimpleNamespace(content=text, reasoning_content="Step 1. ", tool_calls=None))],
            usage=None,
        )
        yield SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", delta=SimpleNamespace(content=None, reasoning_content="Step 2.", tool_calls=None))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    return _stream()


@pytest.mark.asyncio
async def test_siliconflow_disables_thinking_when_reasoning_effort_is_absent() -> None:
    mock_create = AsyncMock(return_value=_fake_chat_response("hello"))
    spec = find_by_name("siliconflow")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = mock_create

        provider = SiliconFlowProvider(
            api_key="siliconflow-test-key",
            api_base="https://api.siliconflow.cn/v1",
            default_model="Pro/zai-org/GLM-4.7",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "你好"}],
            model="Pro/zai-org/GLM-4.7",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["extra_body"]["enable_thinking"] is False
    assert "thinking_budget" not in kwargs["extra_body"]


@pytest.mark.asyncio
async def test_siliconflow_disables_thinking_for_minimal_mode() -> None:
    mock_create = AsyncMock(return_value=_fake_chat_response("hello"))
    spec = find_by_name("siliconflow")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = mock_create

        provider = SiliconFlowProvider(
            api_key="siliconflow-test-key",
            api_base="https://api.siliconflow.cn/v1",
            default_model="Pro/zai-org/GLM-4.7",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "你好"}],
            model="Pro/zai-org/GLM-4.7",
            reasoning_effort="minimal",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["extra_body"]["enable_thinking"] is False
    assert "thinking_budget" not in kwargs["extra_body"]


@pytest.mark.parametrize(
    ("reasoning_effort", "expected_budget"),
    [
        ("low", 1024),
        ("medium", 4096),
        ("high", 8192),
    ],
)
@pytest.mark.asyncio
async def test_siliconflow_enables_thinking_and_sets_budget_for_reasoning_mode(
    reasoning_effort: str,
    expected_budget: int,
) -> None:
    mock_create = AsyncMock(return_value=_fake_chat_response("hello"))
    spec = find_by_name("siliconflow")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = mock_create

        provider = SiliconFlowProvider(
            api_key="siliconflow-test-key",
            api_base="https://api.siliconflow.cn/v1",
            default_model="Pro/zai-org/GLM-4.7",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "你好"}],
            model="Pro/zai-org/GLM-4.7",
            reasoning_effort=reasoning_effort,
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["extra_body"]["enable_thinking"] is True
    assert kwargs["extra_body"]["thinking_budget"] == expected_budget


@pytest.mark.asyncio
async def test_siliconflow_keeps_tool_choice_and_thinking_for_forced_tool_request() -> None:
    mock_create = AsyncMock(return_value=_fake_tool_call_response())
    spec = find_by_name("siliconflow")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = mock_create

        provider = SiliconFlowProvider(
            api_key="siliconflow-test-key",
            api_base="https://api.siliconflow.cn/v1",
            default_model="Pro/zai-org/GLM-4.7",
            spec=spec,
        )
        await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}],
            model="Pro/zai-org/GLM-4.7",
            reasoning_effort="high",
            tool_choice="required",
        )

    kwargs = mock_create.call_args.kwargs
    assert kwargs["tool_choice"] == "required"
    assert kwargs["extra_body"]["enable_thinking"] is True
    assert kwargs["extra_body"]["thinking_budget"] == 8192


@pytest.mark.asyncio
async def test_siliconflow_chat_stream_keeps_openai_stream_path_and_reasoning() -> None:
    spec = find_by_name("siliconflow")

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI") as mock_client:
        client_instance = mock_client.return_value
        client_instance.chat.completions.create = AsyncMock(return_value=_fake_chat_stream("hello"))

        provider = SiliconFlowProvider(
            api_key="siliconflow-test-key",
            api_base="https://api.siliconflow.cn/v1",
            default_model="Pro/zai-org/GLM-4.7",
            spec=spec,
        )
        deltas: list[str] = []

        async def _on_delta(text: str) -> None:
            deltas.append(text)

        result = await provider.chat_stream(
            messages=[{"role": "user", "content": "你好"}],
            model="Pro/zai-org/GLM-4.7",
            on_content_delta=_on_delta,
        )

    assert result.content == "hello"
    assert result.reasoning_content == "Step 1. Step 2."
    assert deltas == ["hello"]
    assert client_instance.chat.completions.create.await_count == 1


def test_siliconflow_never_uses_responses_api() -> None:
    spec = find_by_name("siliconflow")
    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI"):
        provider = SiliconFlowProvider(
            api_key="siliconflow-test-key",
            spec=spec,
            default_model="Pro/zai-org/GLM-4.7",
        )

    assert provider._should_use_responses_api("Pro/zai-org/GLM-4.7", "high") is False
