"""Moonshot/Kimi 独立 provider，收口其 thinking 与 tool_choice 约束。"""

from __future__ import annotations

from typing import Any

from nomi.providers.backends.openai_compat import OpenAICompatProvider


class MoonshotProvider(OpenAICompatProvider):
    """封装 Kimi OpenAI 兼容接口的轻量适配层。"""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "kimi-k2.6",
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
    def _normalize_model_name(model: str | None, default_model: str) -> str:
        """返回归一化后的实际模型名。"""
        return (model or default_model).strip().lower()

    @classmethod
    def _is_optional_thinking_model(cls, model: str | None, default_model: str) -> bool:
        """判断是否是可显式开关 thinking 的 Kimi K2.5/K2.6 模型。"""
        normalized = cls._normalize_model_name(model, default_model)
        return "kimi-k2.6" in normalized or "kimi-k2.5" in normalized

    @classmethod
    def _is_dedicated_thinking_model(cls, model: str | None, default_model: str) -> bool:
        """判断是否是强制启用 thinking 的专用模型。"""
        normalized = cls._normalize_model_name(model, default_model)
        return "kimi-k2-thinking" in normalized

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
        """判断当前请求是否传入了 Kimi 暂不支持的强制工具选择。"""
        if tool_choice == "required":
            return True
        return isinstance(tool_choice, dict)

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
        reasoning_level = reasoning_effort.lower() if isinstance(reasoning_effort, str) else None
        has_reasoning_history = self._has_reasoning_history(messages)

        if self._is_optional_thinking_model(model, self.default_model):
            if reasoning_level == "minimal":
                extra_body["thinking"] = {"type": "disabled"}
            elif reasoning_level is not None:
                thinking: dict[str, Any] = {"type": "enabled"}
                if has_reasoning_history:
                    thinking["keep"] = "all"
                extra_body["thinking"] = thinking
        elif self._is_dedicated_thinking_model(model, self.default_model):
            if reasoning_level and reasoning_level != "minimal" and has_reasoning_history:
                extra_body["thinking"] = {"type": "enabled", "keep": "all"}

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
