"""Qwen 独立 provider，收口阿里百炼的 thinking 请求参数。"""

from __future__ import annotations

from typing import Any

from nomi.providers.backends.openai_compat import OpenAICompatProvider


class QwenProvider(OpenAICompatProvider):
    """封装 Qwen OpenAI 兼容接口的轻量适配层。"""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "qwen-max",
        extra_headers: dict[str, str] | None = None,
        spec=None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            api_base=api_base,
            default_model=default_model,
            extra_headers=extra_headers,
            spec=spec,
        )

    @staticmethod
    def _wants_thinking(reasoning_effort: str | None) -> bool:
        """把 reasoning_effort 映射成 Qwen 的 enable_thinking。"""
        if reasoning_effort is None:
            return False
        return reasoning_effort.lower() != "minimal"

    @staticmethod
    def _has_reasoning_history(messages: list[dict[str, Any]]) -> bool:
        """判断历史中是否已有 assistant reasoning_content。"""
        for message in messages:
            if message.get("role") != "assistant":
                continue
            reasoning_content = message.get("reasoning_content")
            if isinstance(reasoning_content, str) and reasoning_content:
                return True
        return False

    @staticmethod
    def _is_forced_tool_choice(tool_choice: str | dict[str, Any] | None) -> bool:
        """判断当前请求是否显式要求强制调用工具。"""
        if tool_choice == "required":
            return True
        if isinstance(tool_choice, dict):
            function = tool_choice.get("function")
            if isinstance(function, dict) and isinstance(function.get("name"), str) and function["name"]:
                return True
        return False

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
        forced_tool_choice = self._is_forced_tool_choice(tool_choice)
        enable_thinking = self._wants_thinking(reasoning_effort) and not forced_tool_choice

        kwargs = super()._build_kwargs(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            None,
            tool_choice,
        )

        extra_body = dict(kwargs.get("extra_body") or {})
        extra_body["enable_thinking"] = enable_thinking
        if self._has_reasoning_history(messages):
            extra_body["preserve_thinking"] = True
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
