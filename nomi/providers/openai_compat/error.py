"""OpenAI 兼容 provider 的错误提取与兜底处理。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomi.providers.base import LLMProvider, LLMResponse

if TYPE_CHECKING:
    from nomi.providers.factory.registry import ProviderSpec


def extract_error_metadata(e: Exception) -> dict[str, Any]:
    """从异常对象中提取统一错误元数据。"""
    response = getattr(e, "response", None)
    headers = getattr(response, "headers", None)
    payload = (
        getattr(e, "body", None)
        or getattr(e, "doc", None)
        or getattr(response, "text", None)
    )
    if payload is None and response is not None:
        response_json = getattr(response, "json", None)
        if callable(response_json):
            try:
                payload = response_json()
            except Exception:
                payload = None
    error_type, error_code = LLMProvider._extract_error_type_code(payload)

    status_code = getattr(e, "status_code", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)

    should_retry: bool | None = None
    if headers is not None:
        raw = headers.get("x-should-retry")
        if isinstance(raw, str):
            lowered = raw.strip().lower()
            if lowered == "true":
                should_retry = True
            elif lowered == "false":
                should_retry = False

    error_kind: str | None = None
    error_name = e.__class__.__name__.lower()
    if "timeout" in error_name:
        error_kind = "timeout"
    elif "connection" in error_name:
        error_kind = "connection"

    return {
        "error_status_code": int(status_code) if status_code is not None else None,
        "error_kind": error_kind,
        "error_type": error_type,
        "error_code": error_code,
        "error_retry_after_s": LLMProvider._extract_retry_after_from_headers(headers),
        "error_should_retry": should_retry,
    }


def handle_error(
    e: Exception,
    *,
    spec: "ProviderSpec | None" = None,
    api_base: str | None = None,
) -> LLMResponse:
    """把 provider 异常转成统一 LLMResponse。"""
    body = (
        getattr(e, "doc", None)
        or getattr(e, "body", None)
        or getattr(getattr(e, "response", None), "text", None)
    )
    body_text = body if isinstance(body, str) else str(body) if body is not None else ""
    msg = f"Error: {body_text.strip()[:500]}" if body_text.strip() else f"Error calling LLM: {e}"

    text = f"{body_text} {e}".lower()
    if spec and spec.is_local and ("502" in text or "connection" in text or "refused" in text):
        msg += (
            "\nHint: this is a local model endpoint. Check that the local server is reachable at "
            f"{api_base or spec.default_api_base}, and if you are using a proxy/tunnel, make sure it "
            "can reach your local Ollama/vLLM service instead of routing localhost through the remote host."
        )

    response = getattr(e, "response", None)
    retry_after = LLMProvider._extract_retry_after_from_headers(getattr(response, "headers", None))
    if retry_after is None:
        retry_after = LLMProvider._extract_retry_after(msg)
    return LLMResponse(
        content=msg,
        finish_reason="error",
        retry_after=retry_after,
        **extract_error_metadata(e),
    )
