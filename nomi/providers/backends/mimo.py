"""MiMo 独立 provider，实现其专属请求策略。"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from nomi.providers.backends.openai_compat import OpenAICompatProvider
from nomi.providers.base import LLMResponse
from nomi.providers.openai_compat.parse import parse_response


class MiMoProvider(OpenAICompatProvider):
    """封装 MiMo OpenAI 兼容接口的独立适配层。"""

    _RAW_LOG_LIMIT = 1200

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "mimo-v2.5",
        extra_headers: dict[str, str] | None = None,
        spec=None,
    ) -> None:
        headers = dict(extra_headers or {})
        if api_key:
            headers.setdefault("api-key", api_key)
        super().__init__(
            api_key=api_key,
            api_base=api_base,
            default_model=default_model,
            extra_headers=headers,
            spec=spec,
        )

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
        kwargs = super()._build_kwargs(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
        )
        kwargs["temperature"] = temperature
        if "top_p" not in kwargs:
            kwargs["top_p"] = 0.95
        extra_body = dict(kwargs.get("extra_body") or {})
        extra_body["thinking"] = {"type": "disabled"}
        if extra_body:
            kwargs["extra_body"] = extra_body
        return kwargs

    def _should_use_responses_api(
        self,
        model: str | None,
        reasoning_effort: str | None,
    ) -> bool:
        del model, reasoning_effort
        return False

    @classmethod
    def _dump_raw(cls, value: Any) -> str:
        """把原始返回裁剪成日志可读字符串。"""
        try:
            model_dump = getattr(value, "model_dump", None)
            if callable(model_dump):
                payload = model_dump()
            elif isinstance(value, dict):
                payload = value
            else:
                payload = value
            text = json.dumps(payload, ensure_ascii=False, default=str)
        except Exception:
            text = repr(value)
        if len(text) > cls._RAW_LOG_LIMIT:
            return text[:cls._RAW_LOG_LIMIT] + "...(truncated)"
        return text

    def _log_raw_response(self, response: Any, *, stream: bool) -> None:
        """在 MiMo 可疑返回时记录原始 provider 响应。"""
        parsed = self._parse(response)
        raw_preview = self._dump_raw(response)
        parsed_preview = {
            "finish_reason": parsed.finish_reason,
            "has_tool_calls": parsed.has_tool_calls,
            "content_preview": (parsed.content or "")[:200],
            "reasoning_preview": (parsed.reasoning_content or "")[:200],
            "usage": parsed.usage,
        }
        logger.warning(
            "MiMo raw {} response: parsed={}, raw={}",
            "stream" if stream else "chat",
            json.dumps(parsed_preview, ensure_ascii=False),
            raw_preview,
        )

    def _parse(self, response: Any) -> LLMResponse:
        return parse_response(self, response)

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
        """执行一次非流式 MiMo 请求，并在可疑结果时记录原始响应。"""
        try:
            kwargs = self._build_kwargs(
                messages, tools, model, max_tokens, temperature,
                reasoning_effort, tool_choice,
            )
            raw = await self._client.chat.completions.create(**kwargs)
            parsed = self._normalize_reasoning_response(self._parse(raw))
            if tools and (parsed.has_tool_calls or not (parsed.content or "").strip()):
                self._log_raw_response(raw, stream=False)
            return parsed
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
        on_content_delta=None,
    ) -> LLMResponse:
        """执行一次流式 MiMo 请求，并在可疑结果时记录 chunks 摘要。"""
        result = await super().chat_stream(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
            on_content_delta=on_content_delta,
        )
        if tools and (result.has_tool_calls or not (result.content or "").strip()):
            logger.warning(
                "MiMo raw stream response summary: {}",
                json.dumps(
                    {
                        "finish_reason": result.finish_reason,
                        "has_tool_calls": result.has_tool_calls,
                        "content_preview": (result.content or "")[:200],
                        "reasoning_preview": (result.reasoning_content or "")[:200],
                        "usage": result.usage,
                    },
                    ensure_ascii=False,
                ),
            )
        return result
