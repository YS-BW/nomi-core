"""provider 解析策略测试。"""

from __future__ import annotations

import pytest

from nomi.config.schema import Config
from nomi.providers.factory.resolution import resolve_provider


def test_resolution_prefers_explicit_openai_prefix() -> None:
    """显式前缀为 openai 时应命中对应 provider。"""
    config = Config()
    config.agents.defaults.provider = "auto"
    config.providers.openai.model = "openai/gpt-4.1"

    resolution = resolve_provider(config)

    assert resolution.provider_name == "openai"
    assert resolution.backend == "openai_compat"
    assert resolution.api_base is None


def test_resolution_prefers_explicit_anthropic_prefix() -> None:
    """显式前缀为 anthropic 时应命中对应 provider。"""
    config = Config()
    config.agents.defaults.provider = "auto"
    config.providers.anthropic.model = "anthropic/claude-sonnet-4-20250514"

    resolution = resolve_provider(config)

    assert resolution.provider_name == "anthropic"
    assert resolution.backend == "anthropic"
    assert resolution.api_base is None


def test_resolution_uses_forced_mimo_provider() -> None:
    """显式配置 mimo 时应直接命中 mimo，并锁定默认地址。"""
    config = Config.model_validate(
        {
            "providers": {
                "mimo": {
                    "apiKey": "custom-test-key",
                    "apiBase": "https://api.xiaomimimo.com/v1",
                }
            },
            "agents": {"defaults": {"provider": "mimo"}},
        }
    )

    resolution = resolve_provider(config)

    assert resolution.provider_name == "mimo"
    assert resolution.backend == "mimo"
    assert resolution.api_base == "https://api.xiaomimimo.com/v1"


def test_resolution_ignores_locked_non_custom_api_base_override() -> None:
    """非 custom provider 即使旧配置里有 apiBase，也应使用注册表默认地址。"""
    config = Config.model_validate(
        {
            "providers": {
                "deepseek": {
                    "apiKey": "deepseek-test-key",
                    "apiBase": "https://proxy.example.com/v1",
                }
            },
            "agents": {"defaults": {"provider": "deepseek"}},
        }
    )

    resolution = resolve_provider(config)

    assert resolution.provider_name == "deepseek"
    assert resolution.api_base == "https://api.deepseek.com"


def test_resolution_allows_custom_api_base_override() -> None:
    """custom provider 仍允许显式配置 apiBase。"""
    config = Config.model_validate(
        {
            "providers": {
                "custom": {
                    "apiKey": "custom-test-key",
                    "apiBase": "https://proxy.example.com/v1",
                    "model": "custom/model",
                }
            },
            "agents": {"defaults": {"provider": "custom"}},
        }
    )

    resolution = resolve_provider(config)

    assert resolution.provider_name == "custom"
    assert resolution.api_base == "https://proxy.example.com/v1"


def test_resolution_routes_mimo_model_to_mimo_provider() -> None:
    """mimo-* 模型在 auto 模式下应直接路由到 mimo backend。"""
    config = Config.model_validate(
        {
            "providers": {
                "mimo": {
                    "apiKey": "mimo-test-key",
                }
            },
            "agents": {"defaults": {"provider": "auto"}},
        }
    )

    resolution = resolve_provider(config)

    assert resolution.provider_name == "mimo"
    assert resolution.backend == "mimo"
    assert resolution.api_base == "https://api.xiaomimimo.com/v1"


def test_resolution_allows_explicit_ollama_prefix_without_api_key() -> None:
    """本地 provider 不要求 API Key 即可通过显式前缀命中。"""
    config = Config()
    config.agents.defaults.provider = "auto"
    config.providers.ollama.model = "ollama/llama3.2"

    resolution = resolve_provider(config)

    assert resolution.provider_name == "ollama"
    assert resolution.api_base == "http://localhost:11434/v1"


def test_resolution_detects_local_provider_by_api_base() -> None:
    """无前缀模型名时，应能通过本地 api_base 识别 provider。"""
    config = Config.model_validate(
        {
            "providers": {"ollama": {"apiBase": "http://127.0.0.1:11434/v1"}},
            "agents": {"defaults": {"provider": "auto"}},
        }
    )
    config.providers.ollama.model = "llama3.2"

    resolution = resolve_provider(config)

    assert resolution.provider_name == "ollama"
    assert resolution.api_base == "http://localhost:11434/v1"


def test_resolution_uses_gateway_fallback_when_model_is_generic() -> None:
    """没有模型关键字时，应回退到可用网关 provider。"""
    config = Config.model_validate(
        {
            "providers": {"openrouter": {"apiKey": "sk-or-test"}},
            "agents": {"defaults": {"provider": "auto"}},
        }
    )
    config.providers.openrouter.model = "grok-4-fast"

    resolution = resolve_provider(config)

    assert resolution.provider_name == "openrouter"
    assert resolution.api_base == "https://openrouter.ai/api/v1"


def test_resolution_uses_forced_provider_and_infers_default_api_base() -> None:
    """强制指定本地 provider 时应推断默认 api_base。"""
    config = Config()
    config.agents.defaults.provider = "ollama"
    config.providers.ollama.model = "llama3.2"

    resolution = resolve_provider(config)

    assert resolution.provider_name == "ollama"
    assert resolution.api_base == "http://localhost:11434/v1"


def test_resolution_uses_forced_deepseek_provider_and_default_base() -> None:
    """显式配置 DeepSeek 时应自动补官方默认 api_base。"""
    config = Config.model_validate(
        {
            "providers": {
                "deepseek": {
                    "apiKey": "deepseek-test-key",
                }
            },
            "agents": {
                "defaults": {
                    "provider": "deepseek",
                }
            },
        }
    )
    config.providers.deepseek.model = "deepseek-v4-flash"

    resolution = resolve_provider(config)

    assert resolution.provider_name == "deepseek"
    assert resolution.backend == "deepseek"
    assert resolution.api_base == "https://api.deepseek.com"


def test_resolution_uses_forced_qwen_provider_and_default_base() -> None:
    """显式配置 Qwen 时应落到 qwen backend 并补默认 api_base。"""
    config = Config.model_validate(
        {
            "providers": {
                "qwen": {
                    "apiKey": "dashscope-test-key",
                }
            },
            "agents": {
                "defaults": {
                    "provider": "qwen",
                }
            },
        }
    )
    config.providers.qwen.model = "qwen-max"

    resolution = resolve_provider(config)

    assert resolution.provider_name == "qwen"
    assert resolution.backend == "qwen"
    assert resolution.api_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_resolution_uses_forced_zhipu_provider_and_default_base() -> None:
    """显式配置 Zhipu 时应落到 zhipu backend 并补默认 api_base。"""
    config = Config.model_validate(
        {
            "providers": {
                "zhipu": {
                    "apiKey": "zhipu-test-key",
                }
            },
            "agents": {
                "defaults": {
                    "provider": "zhipu",
                }
            },
        }
    )
    config.providers.zhipu.model = "glm-4.5"

    resolution = resolve_provider(config)

    assert resolution.provider_name == "zhipu"
    assert resolution.backend == "zhipu"
    assert resolution.api_base == "https://open.bigmodel.cn/api/paas/v4"


def test_resolution_uses_forced_minimax_provider_and_default_base() -> None:
    """显式配置 MiniMax 时应落到 Anthropic backend 并补默认 api_base。"""
    config = Config.model_validate(
        {
            "providers": {
                "minimax": {
                    "apiKey": "minimax-test-key",
                }
            },
            "agents": {
                "defaults": {
                    "provider": "minimax",
                }
            },
        }
    )
    config.providers.minimax.model = "MiniMax-M2.7"

    resolution = resolve_provider(config)

    assert resolution.provider_name == "minimax"
    assert resolution.backend == "anthropic"
    assert resolution.api_base == "https://api.minimaxi.com/anthropic"


def test_resolution_uses_forced_moonshot_provider_and_default_base() -> None:
    """显式配置 Moonshot 时应落到专用 backend 并补默认 api_base。"""
    config = Config.model_validate(
        {
            "providers": {
                "moonshot": {
                    "apiKey": "moonshot-test-key",
                }
            },
            "agents": {
                "defaults": {
                    "provider": "moonshot",
                }
            },
        }
    )
    config.providers.moonshot.model = "kimi-k2.6"

    resolution = resolve_provider(config)

    assert resolution.provider_name == "moonshot"
    assert resolution.backend == "moonshot"
    assert resolution.api_base == "https://api.moonshot.cn/v1"


def test_resolution_uses_forced_siliconflow_provider_and_default_base() -> None:
    """显式配置 SiliconFlow 时应落到专用 backend 并补默认 api_base。"""
    config = Config.model_validate(
        {
            "providers": {
                "siliconflow": {
                    "apiKey": "siliconflow-test-key",
                }
            },
            "agents": {
                "defaults": {
                    "provider": "siliconflow",
                }
            },
        }
    )
    config.providers.siliconflow.model = "Pro/zai-org/GLM-4.7"

    resolution = resolve_provider(config)

    assert resolution.provider_name == "siliconflow"
    assert resolution.backend == "siliconflow"
    assert resolution.api_base == "https://api.siliconflow.cn/v1"


def test_resolution_rejects_unknown_forced_provider() -> None:
    """未知强制 provider 应立即报错。"""
    config = Config()
    config.agents.defaults.provider = "missing-provider"

    with pytest.raises(ValueError, match="Unknown provider configured: missing-provider"):
        resolve_provider(config)
