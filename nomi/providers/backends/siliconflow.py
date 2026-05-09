"""SiliconFlow 独立 provider，收口其 thinking 请求参数。"""

from __future__ import annotations

from nomi.providers.backends.openai_compat import OpenAICompatProvider


class SiliconFlowProvider(OpenAICompatProvider):
    """封装 SiliconFlow OpenAI 兼容接口的轻量适配层。"""

    _THINKING_BUDGETS = {
        "low": 1024,
        "medium": 4096,
        "high": 8192,
    }

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "Pro/zai-org/GLM-4.7",
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
    def _normalize_reasoning_effort(reasoning_effort: str | None) -> str | None:
        """返回归一化后的 reasoning_effort。"""
        if reasoning_effort is None:
            return None
        return reasoning_effort.lower()

    @classmethod
    def _wants_thinking(cls, reasoning_effort: str | None) -> bool:
        """把 reasoning_effort 映射成 SiliconFlow 的 enable_thinking。"""
        normalized = cls._normalize_reasoning_effort(reasoning_effort)
        if normalized is None:
            return False
        return normalized != "minimal"

    @classmethod
    def _thinking_budget_for_effort(cls, reasoning_effort: str | None) -> int | None:
        """把 reasoning_effort 映射成 SiliconFlow 的 thinking_budget。"""
        normalized = cls._normalize_reasoning_effort(reasoning_effort)
        if normalized is None:
            return None
        return cls._THINKING_BUDGETS.get(normalized)

    def _build_kwargs(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, object] | None,
    ) -> dict[str, object]:
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
        enable_thinking = self._wants_thinking(reasoning_effort)
        extra_body["enable_thinking"] = enable_thinking
        thinking_budget = self._thinking_budget_for_effort(reasoning_effort)
        if thinking_budget is not None:
            extra_body["thinking_budget"] = thinking_budget
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
