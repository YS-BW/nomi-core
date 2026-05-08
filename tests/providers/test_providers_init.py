"""Tests for lazy provider exports from nomi.providers."""

from __future__ import annotations

import importlib
import sys


def test_importing_providers_package_is_lazy(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "nomi.providers", raising=False)
    monkeypatch.delitem(sys.modules, "nomi.providers.backends.anthropic", raising=False)
    monkeypatch.delitem(sys.modules, "nomi.providers.backends.openai_compat", raising=False)
    monkeypatch.delitem(sys.modules, "nomi.providers.backends.azure_openai", raising=False)

    providers = importlib.import_module("nomi.providers")

    assert "nomi.providers.backends.anthropic" not in sys.modules
    assert "nomi.providers.backends.openai_compat" not in sys.modules
    assert "nomi.providers.backends.azure_openai" not in sys.modules
    assert providers.__all__ == [
        "LLMProvider",
        "LLMResponse",
        "AnthropicProvider",
        "OpenAICompatProvider",
        "AzureOpenAIProvider",
    ]


def test_explicit_provider_import_still_works(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "nomi.providers", raising=False)
    monkeypatch.delitem(sys.modules, "nomi.providers.backends.anthropic", raising=False)

    namespace: dict[str, object] = {}
    exec("from nomi.providers import AnthropicProvider", namespace)

    assert namespace["AnthropicProvider"].__name__ == "AnthropicProvider"
    assert "nomi.providers.backends.anthropic" in sys.modules
