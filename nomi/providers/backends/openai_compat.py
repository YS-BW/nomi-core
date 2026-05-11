"""OpenAI 兼容提供方，统一承接非 Anthropic 的主流接口。"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if os.environ.get("LANGFUSE_SECRET_KEY") and importlib.util.find_spec("langfuse"):
    from langfuse.openai import AsyncOpenAI
else:
    if os.environ.get("LANGFUSE_SECRET_KEY"):
        import logging
        logging.getLogger(__name__).warning(
            "LANGFUSE_SECRET_KEY is set but langfuse is not installed; "
            "install with `pip install langfuse` to enable tracing"
        )
    from openai import AsyncOpenAI

from nomi.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nomi.providers.openai_compat.common import (
    DEFAULT_OPENROUTER_HEADERS,
    extract_usage,
    maybe_mapping,
    uses_openrouter_attribution,
)
from nomi.providers.openai_compat.error import (
    extract_error_metadata,
    handle_error,
)
from nomi.providers.openai_compat.parse import parse_chunks, parse_response
from nomi.providers.openai_compat.request import (
    apply_cache_control,
    build_kwargs,
    build_responses_body,
    normalize_tool_call_id,
    sanitize_messages,
    should_fallback_from_responses_error,
    should_use_responses_api,
    supports_temperature,
)
from nomi.providers.openai_responses import (
    consume_sdk_stream,
    parse_response_output,
)

if TYPE_CHECKING:
    from nomi.providers.factory.registry import ProviderSpec


class OpenAICompatProvider(LLMProvider):
    """统一封装 OpenAI 兼容接口的请求构造、解析与回退逻辑。"""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "gpt-4o",
        extra_headers: dict[str, str] | None = None,
        spec: ProviderSpec | None = None,
    ):
        """初始化 OpenAI 兼容提供方。

        参数:
            api_key: 提供方 API Key。
            api_base: 提供方基础地址。
            default_model: 默认模型名称。
            extra_headers: 额外请求头。
            spec: 已解析好的提供方规格。

        返回:
            无返回值。
        """
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}
        self._spec = spec

        if api_key and spec and spec.env_key:
            self._setup_env(api_key, api_base)

        effective_base = api_base or (spec.default_api_base if spec else None) or None
        self._effective_base = effective_base
        default_headers = {"x-session-affinity": uuid.uuid4().hex}
        if uses_openrouter_attribution(spec, effective_base):
            default_headers.update(DEFAULT_OPENROUTER_HEADERS)
        if extra_headers:
            default_headers.update(extra_headers)

        self._client = AsyncOpenAI(
            api_key=api_key or "no-key",
            base_url=effective_base,
            default_headers=default_headers,
            max_retries=0,
        )

    def _normalize_reasoning_request_message(self, message: dict[str, Any]) -> None:
        """为请求消息保留统一的推理字段归一化扩展点。

        参数:
            message: 已完成基础清洗、准备发送给模型的单条消息；默认不做修改。

        返回:
            无返回值。
        """
        del message

    def _normalize_reasoning_response(self, response: LLMResponse) -> LLMResponse:
        """为响应结果保留统一的推理字段归一化扩展点。

        参数:
            response: 已解析成统一结构的模型响应。

        返回:
            默认直接返回原响应对象。
        """
        return response

    def _setup_env(self, api_key: str, api_base: str | None) -> None:
        """Set environment variables based on provider spec."""
        spec = self._spec
        if not spec or not spec.env_key:
            return
        if spec.is_gateway:
            os.environ[spec.env_key] = api_key
        else:
            os.environ.setdefault(spec.env_key, api_key)
        effective_base = api_base or spec.default_api_base
        for env_name, env_val in spec.env_extras:
            resolved = env_val.replace("{api_key}", api_key).replace("{api_base}", effective_base)
            os.environ.setdefault(env_name, resolved)

    @classmethod
    def _apply_cache_control(
        cls,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        """Inject cache_control markers for prompt caching."""
        return apply_cache_control(messages, tools)

    @staticmethod
    def _normalize_tool_call_id(tool_call_id: Any) -> Any:
        """Normalize to a provider-safe 9-char alphanumeric form."""
        return normalize_tool_call_id(tool_call_id)

    def _sanitize_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Strip non-standard keys, normalize tool_call IDs."""
        return sanitize_messages(self, messages)

    # 请求参数在这里一次性收口，避免上层散落处理不同兼容分支。

    @staticmethod
    def _supports_temperature(
        model_name: str,
        reasoning_effort: str | None = None,
    ) -> bool:
        """Return True when the model accepts a temperature parameter.

        GPT-5 family and reasoning models (o1/o3/o4) reject temperature
        when reasoning_effort is set to anything other than ``"none"``.
        """
        return supports_temperature(model_name, reasoning_effort)

    def _build_kwargs(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
    ) -> dict[str, Any]:
        return build_kwargs(
            self,
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
        )

    def _should_use_responses_api(
        self,
        model: str | None,
        reasoning_effort: str | None,
    ) -> bool:
        """Use Responses API only for direct OpenAI requests that benefit from it."""
        return should_use_responses_api(self, model, reasoning_effort)

    @staticmethod
    def _should_fallback_from_responses_error(e: Exception) -> bool:
        """Fallback only for likely Responses API compatibility errors."""
        return should_fallback_from_responses_error(e)

    def _build_responses_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Build a Responses API body for direct OpenAI requests."""
        return build_responses_body(
            self,
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
        )

    # 解析逻辑统一返回标准 LLMResponse，主循环无需了解各家字段差异。

    @staticmethod
    def _maybe_mapping(value: Any) -> dict[str, Any] | None:
        return maybe_mapping(value)

    @classmethod
    def _extract_text_content(cls, value: Any) -> str | None:
        from nomi.providers.openai_compat.common import extract_text_content

        return extract_text_content(value)

    @classmethod
    def _extract_usage(cls, response: Any) -> dict[str, int]:
        return extract_usage(response)

    @staticmethod
    def _get_nested_int(obj: Any, path: tuple[str, ...]) -> int:
        from nomi.providers.openai_compat.common import get_nested_int

        return get_nested_int(obj, path)

    @staticmethod
    def _coerce_pseudo_parameter_value(raw_value: str) -> Any:
        from nomi.providers.openai_compat.common import coerce_pseudo_parameter_value

        return coerce_pseudo_parameter_value(raw_value)

    @staticmethod
    def _normalize_tool_arguments(
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """返回工具参数的浅拷贝，保留当前协议原样。"""
        from nomi.providers.openai_compat.common import normalize_tool_arguments

        return normalize_tool_arguments(tool_name, arguments)

    @classmethod
    def _extract_pseudo_tool_calls(
        cls,
        content: str | None,
    ) -> tuple[str | None, list[ToolCallRequest]]:
        """把某些兼容模型输出的伪 XML 工具调用文本恢复成结构化 tool_calls。"""
        from nomi.providers.openai_compat.common import extract_pseudo_tool_calls

        return extract_pseudo_tool_calls(content)

    def _parse(self, response: Any) -> LLMResponse:
        return parse_response(self, response)

    @classmethod
    def _parse_chunks(cls, chunks: list[Any]) -> LLMResponse:
        return parse_chunks(chunks)

    @classmethod
    def _extract_error_metadata(cls, e: Exception) -> dict[str, Any]:
        return extract_error_metadata(e)

    @staticmethod
    def _handle_error(
        e: Exception,
        *,
        spec: ProviderSpec | None = None,
        api_base: str | None = None,
    ) -> LLMResponse:
        return handle_error(e, spec=spec, api_base=api_base)

    # 对外只暴露标准 chat / chat_stream 接口，方便主链路统一调度。

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        """执行一次非流式 OpenAI 兼容请求。

        参数:
            messages: 消息列表。
            tools: 可选工具定义。
            model: 指定模型名称。
            max_tokens: 最大输出 token 数。
            temperature: 采样温度。
            reasoning_effort: 推理强度配置。
            tool_choice: 工具选择策略。

        返回:
            标准化后的模型响应。
        """
        try:
            if self._should_use_responses_api(model, reasoning_effort):
                try:
                    body = self._build_responses_body(
                        messages, tools, model, max_tokens, temperature,
                        reasoning_effort, tool_choice,
                    )
                    return self._normalize_reasoning_response(
                        parse_response_output(await self._client.responses.create(**body))
                    )
                except Exception as responses_error:
                    if not self._should_fallback_from_responses_error(responses_error):
                        raise

            kwargs = self._build_kwargs(
                messages, tools, model, max_tokens, temperature,
                reasoning_effort, tool_choice,
            )
            return self._normalize_reasoning_response(
                self._parse(await self._client.chat.completions.create(**kwargs))
            )
        except Exception as e:
            return self._handle_error(e, spec=self._spec, api_base=self.api_base)

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """执行一次流式 OpenAI 兼容请求。

        参数:
            messages: 消息列表。
            tools: 可选工具定义。
            model: 指定模型名称。
            max_tokens: 最大输出 token 数。
            temperature: 采样温度。
            reasoning_effort: 推理强度配置。
            tool_choice: 工具选择策略。
            on_content_delta: 文本流回调。

        返回:
            标准化后的模型响应。
        """
        idle_timeout_s = int(os.environ.get("NANOBOT_STREAM_IDLE_TIMEOUT_S", "90"))
        try:
            if self._should_use_responses_api(model, reasoning_effort):
                try:
                    body = self._build_responses_body(
                        messages, tools, model, max_tokens, temperature,
                        reasoning_effort, tool_choice,
                    )
                    body["stream"] = True
                    stream = await self._client.responses.create(**body)

                    async def _timed_stream():
                        stream_iter = stream.__aiter__()
                        while True:
                            try:
                                yield await asyncio.wait_for(
                                    stream_iter.__anext__(),
                                    timeout=idle_timeout_s,
                                )
                            except StopAsyncIteration:
                                break

                    content, tool_calls, finish_reason, usage, reasoning_content, reasoning_items = await consume_sdk_stream(
                        _timed_stream(),
                        on_content_delta,
                    )
                    return self._normalize_reasoning_response(
                        LLMResponse(
                            content=content or None,
                            tool_calls=tool_calls,
                            finish_reason=finish_reason,
                            usage=usage,
                            reasoning_content=reasoning_content,
                            reasoning_items=reasoning_items,
                        )
                    )
                except Exception as responses_error:
                    if not self._should_fallback_from_responses_error(responses_error):
                        raise

            kwargs = self._build_kwargs(
                messages, tools, model, max_tokens, temperature,
                reasoning_effort, tool_choice,
            )
            kwargs["stream"] = True
            kwargs["stream_options"] = {"include_usage": True}
            stream = await self._client.chat.completions.create(**kwargs)
            chunks: list[Any] = []
            stream_iter = stream.__aiter__()
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        stream_iter.__anext__(),
                        timeout=idle_timeout_s,
                    )
                except StopAsyncIteration:
                    break
                chunks.append(chunk)
                if on_content_delta and chunk.choices:
                    text = getattr(chunk.choices[0].delta, "content", None)
                    if text:
                        await on_content_delta(text)
            return self._normalize_reasoning_response(self._parse_chunks(chunks))
        except asyncio.TimeoutError:
            return LLMResponse(
                content=(
                    f"Error calling LLM: stream stalled for more than "
                    f"{idle_timeout_s} seconds"
                ),
                finish_reason="error",
                error_kind="timeout",
            )
        except Exception as e:
            return self._handle_error(e, spec=self._spec, api_base=self.api_base)

    def get_default_model(self) -> str:
        """返回 OpenAI 兼容提供方的默认模型。

        返回:
            当前默认模型名称。
        """
        return self.default_model
