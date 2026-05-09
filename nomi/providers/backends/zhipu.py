"""Zhipu 独立 provider，收口其 thinking 与工具选择参数。"""

from __future__ import annotations

from typing import Any

from nomi.providers.backends.openai_compat import OpenAICompatProvider


class ZhipuProvider(OpenAICompatProvider):
    """封装智谱 OpenAI 兼容接口的轻量适配层。"""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "glm-4.5",
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
        """把 reasoning_effort 映射成智谱 thinking 开关。"""
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
    def _needs_tool_choice_downgrade(tool_choice: str | dict[str, Any] | None) -> bool:
        """判断当前请求是否传入了智谱不支持的强制工具选择。"""
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
        downgraded_tool_choice = "auto" if self._needs_tool_choice_downgrade(tool_choice) else tool_choice
        enable_thinking = self._wants_thinking(reasoning_effort)

        kwargs = super()._build_kwargs(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            None,
            downgraded_tool_choice,
        )

        extra_body = dict(kwargs.get("extra_body") or {})
        if enable_thinking:
            thinking: dict[str, Any] = {"type": "enabled"}
            if self._has_reasoning_history(messages):
                thinking["clear_thinking"] = False
            extra_body["thinking"] = thinking
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
