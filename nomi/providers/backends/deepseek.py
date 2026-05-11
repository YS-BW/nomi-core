"""DeepSeek 独立 provider，收口其思考模式与工具回放语义。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from nomi.providers.backends.openai_compat import OpenAICompatProvider
from nomi.providers.base import LLMProvider, LLMResponse
from nomi.providers.openai_compat.common import ALLOWED_MSG_KEYS
from nomi.providers.openai_compat.request import normalize_tool_call_id, supports_temperature


class DeepSeekProvider(OpenAICompatProvider):
    """封装 DeepSeek OpenAI 兼容接口的专属适配层。"""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "deepseek-chat",
        extra_headers: dict[str, str] | None = None,
        spec=None,
    ) -> None:
        """初始化 DeepSeek 适配器并记录当前活跃模型名。"""
        super().__init__(
            api_key=api_key,
            api_base=api_base,
            default_model=default_model,
            extra_headers=extra_headers,
            spec=spec,
        )
        self._active_model_name = default_model

    @staticmethod
    def _is_reasoner_model(model_name: str) -> bool:
        """判断是否是 DeepSeek R1 兼容推理模型。"""
        normalized = model_name.lower().split("/", 1)[-1]
        return normalized == "deepseek-reasoner"

    @staticmethod
    def _is_thinking_v4_model(model_name: str) -> bool:
        """判断是否是 DeepSeek V4 thinking 模型。"""
        normalized = model_name.lower().split("/", 1)[-1]
        return normalized.startswith("deepseek-v4-")

    def _sanitize_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按 DeepSeek 规则保留工具回放消息的原始形态。"""
        model_name = self._active_model_name or self.default_model
        is_reasoner = self._is_reasoner_model(model_name)

        sanitized = LLMProvider._sanitize_request_messages(messages, ALLOWED_MSG_KEYS)
        id_map: dict[str, str] = {}

        def map_id(value: Any) -> Any:
            """为 DeepSeek 工具调用 ID 建立稳定映射。"""
            if not isinstance(value, str):
                return value
            return id_map.setdefault(value, normalize_tool_call_id(value))

        for clean in sanitized:
            if clean.get("role") == "assistant" and is_reasoner:
                clean.pop("reasoning_content", None)
                clean.pop("reasoning_items", None)

            if isinstance(clean.get("tool_calls"), list):
                normalized_calls = []
                for tc in clean["tool_calls"]:
                    if not isinstance(tc, dict):
                        normalized_calls.append(tc)
                        continue
                    tc_clean = dict(tc)
                    tc_clean["id"] = map_id(tc_clean.get("id"))
                    normalized_calls.append(tc_clean)
                clean["tool_calls"] = normalized_calls
                # DeepSeek thinking + tool calls 需要尽量回放原始 assistant message，
                # 这里不能像 generic OpenAI 兼容分支那样把空字符串改写成 None。
                if clean.get("role") == "assistant" and "content" not in clean:
                    clean["content"] = ""

            if "tool_call_id" in clean and clean["tool_call_id"]:
                clean["tool_call_id"] = map_id(clean["tool_call_id"])

        return self._enforce_role_alternation(sanitized)

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
        """构造 DeepSeek Chat Completions 参数。"""
        model_name = model or self.default_model
        self._active_model_name = model_name

        spec = self._spec
        if spec and spec.strip_model_prefix:
            model_name = model_name.split("/")[-1]

        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": self._sanitize_messages(
                self._sanitize_empty_content(messages),
            ),
        }

        if supports_temperature(model_name, reasoning_effort):
            kwargs["temperature"] = temperature
        kwargs["max_tokens"] = max(1, max_tokens)

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"

        return kwargs

    def _should_use_responses_api(
        self,
        model: str | None,
        reasoning_effort: str | None,
    ) -> bool:
        del model, reasoning_effort
        return False

    def _unsupported_reasoner_tools_response(self) -> LLMResponse:
        """对 deepseek-reasoner 的工具调用限制给出明确错误。"""
        return LLMResponse(
            content=(
                "Error calling LLM: DeepSeek `deepseek-reasoner` 暂不支持 Function Calling。"
                " 请改用 `deepseek-v4-flash`、`deepseek-v4-pro` 或关闭工具后再试。"
            ),
            finish_reason="error",
        )

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
        """执行一次非流式 DeepSeek 请求。"""
        model_name = model or self.default_model
        if tools and self._is_reasoner_model(model_name):
            return self._unsupported_reasoner_tools_response()
        return await super().chat(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
        )

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
        """DeepSeek 在 thinking + tool calls 下优先走非流式，避免回放语义被流式兼容链路破坏。"""
        model_name = model or self.default_model
        if tools and self._is_reasoner_model(model_name):
            return self._unsupported_reasoner_tools_response()

        if tools and self._is_thinking_v4_model(model_name):
            result = await self.chat(
                messages=messages,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                tool_choice=tool_choice,
            )
            if on_content_delta and result.content:
                await on_content_delta(result.content)
            return result

        return await super().chat_stream(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            tool_choice=tool_choice,
            on_content_delta=on_content_delta,
        )
