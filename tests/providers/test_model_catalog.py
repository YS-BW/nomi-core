"""provider 模型目录测试。"""

from __future__ import annotations

from nomi.providers.factory.model_catalog import (
    find_model,
    get_model_context_limit,
    list_models,
    suggest_models,
)


def test_list_models_returns_mimo_catalog() -> None:
    """默认 mimo provider 应返回内置模型目录。"""
    models = list_models("mimo")

    names = [item.name for item in models]
    assert "mimo-v2.5" in names


def test_list_models_returns_deepseek_catalog() -> None:
    """DeepSeek provider 应返回内置模型目录。"""
    models = list_models("deepseek")

    names = [item.name for item in models]
    assert "deepseek-v4-flash" in names
    assert "deepseek-v4-pro" in names


def test_list_models_returns_qwen_catalog() -> None:
    """Qwen provider 应返回内置模型目录。"""
    models = list_models("qwen")

    names = [item.name for item in models]
    assert "qwen-max" in names
    assert "qwen3-32b" in names


def test_list_models_returns_minimax_catalog() -> None:
    """MiniMax provider 应返回内置模型目录。"""
    models = list_models("minimax")

    names = [item.name for item in models]
    assert "MiniMax-M2.7" in names
    assert "MiniMax-M2.7-highspeed" in names


def test_list_models_returns_moonshot_catalog() -> None:
    """Moonshot provider 应返回内置模型目录。"""
    models = list_models("moonshot")

    names = [item.name for item in models]
    assert "kimi-k2.6" in names
    assert "kimi-k2-thinking" in names


def test_list_models_returns_siliconflow_catalog() -> None:
    """SiliconFlow provider 应返回内置模型目录。"""
    models = list_models("siliconflow")

    names = [item.name for item in models]
    assert "Pro/zai-org/GLM-4.7" in names
    assert "Pro/deepseek-ai/DeepSeek-V3.2" in names


def test_find_model_accepts_prefixed_alias() -> None:
    """带 provider 前缀的模型名应能命中目录条目。"""
    model = find_model("anthropic/claude-sonnet-4-20250514")

    assert model is not None
    assert model.provider_name == "anthropic"
    assert model.name == "claude-sonnet-4-20250514"


def test_suggest_models_filters_by_prefix() -> None:
    """模型补全应按输入前缀过滤。"""
    suggestions = suggest_models("gpt", provider="openai")

    assert "gpt-5" in suggestions
    assert "gpt-4.1" in suggestions


def test_suggest_models_supports_qwen_prefix() -> None:
    """Qwen 模型补全应支持品牌前缀过滤。"""
    suggestions = suggest_models("qwen3", provider="qwen")

    assert "qwen3-32b" in suggestions


def test_suggest_models_supports_minimax_prefix() -> None:
    """MiniMax 模型补全应支持品牌前缀过滤。"""
    suggestions = suggest_models("m2.7", provider="minimax")

    assert "MiniMax-M2.7" in suggestions


def test_suggest_models_supports_moonshot_prefix() -> None:
    """Moonshot 模型补全应支持 Kimi 前缀过滤。"""
    suggestions = suggest_models("kimi-k2", provider="moonshot")

    assert "kimi-k2.6" in suggestions
    assert "kimi-k2-thinking" in suggestions


def test_suggest_models_supports_siliconflow_prefix() -> None:
    """SiliconFlow 模型补全应支持组织前缀过滤。"""
    suggestions = suggest_models("glm-4.7", provider="siliconflow")

    assert "Pro/zai-org/GLM-4.7" in suggestions


def test_get_model_context_limit_returns_known_hint() -> None:
    """目录内模型应返回推荐上下文窗口。"""
    assert get_model_context_limit("mimo-v2.5", provider="mimo") == 65_536


def test_unsupported_provider_returns_empty_catalog() -> None:
    """未覆盖的 provider 应返回空建议与空推荐值。"""
    assert list_models("ollama") == []
    assert suggest_models("llama", provider="ollama") == []
    assert get_model_context_limit("llama3.2", provider="ollama") is None
