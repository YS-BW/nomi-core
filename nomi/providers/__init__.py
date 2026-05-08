"""提供方抽象与延迟导出入口。"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from nomi.providers.base import LLMProvider, LLMResponse

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "AnthropicProvider",
    "MiMoProvider",
    "OpenAICompatProvider",
    "AzureOpenAIProvider",
]

_LAZY_IMPORTS = {
    "AnthropicProvider": ".backends.anthropic",
    "MiMoProvider": ".backends.mimo",
    "OpenAICompatProvider": ".backends.openai_compat",
    "AzureOpenAIProvider": ".backends.azure_openai",
}

if TYPE_CHECKING:
    from nomi.providers.backends.anthropic import AnthropicProvider
    from nomi.providers.backends.azure_openai import AzureOpenAIProvider
    from nomi.providers.backends.mimo import MiMoProvider
    from nomi.providers.backends.openai_compat import OpenAICompatProvider


def __getattr__(name: str):
    """按需导出提供方实现。

    参数:
        name: 需要获取的提供方类名。

    返回:
        对应名称的提供方类对象。
    """
    module_name = _LAZY_IMPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    return getattr(module, name)
