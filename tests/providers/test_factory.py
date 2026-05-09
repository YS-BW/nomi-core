"""provider 装配入口测试。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nomi.config.schema import Config
from nomi.providers.factory.build import build_provider


def test_build_provider_uses_forced_openai_backend() -> None:
    """显式指定 openai 时应装配对应 backend。"""
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "openai",
                    "model": "gpt-4.1",
                }
            },
            "providers": {"openai": {"apiKey": "openai-test-key"}},
        }
    )

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI"):
        provider = build_provider(config)

    assert provider.__class__.__name__ == "OpenAICompatProvider"
    assert provider._spec is not None
    assert provider._spec.name == "openai"


def test_build_provider_uses_mimo_for_default_first_run() -> None:
    """首次默认主链路应装配 mimo provider。"""
    config = Config.model_validate(
        {
            "providers": {
                "mimo": {
                    "apiKey": "mimo-test-key",
                    "apiBase": "https://api.xiaomimimo.com/v1",
                }
            },
        }
    )

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI"):
        provider = build_provider(config)

    assert provider.__class__.__name__ == "MiMoProvider"
    assert provider.get_default_model() == "mimo-v2.5"
    assert provider._spec is not None
    assert provider._spec.name == "mimo"
    assert provider._effective_base == "https://api.xiaomimimo.com/v1"


def test_build_provider_applies_default_generation_settings() -> None:
    """provider 应继承配置里的默认 generation 参数。"""
    config = Config.model_validate(
        {
            "providers": {"mimo": {"apiKey": "mimo-test-key"}},
            "agents": {
                "defaults": {
                    "provider": "mimo",
                    "model": "mimo-v2.5",
                    "temperature": 0.6,
                    "max_tokens": 4096,
                    "reasoning_effort": "medium",
                }
            },
        }
    )

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI"):
        provider = build_provider(config)

    assert provider.generation.temperature == pytest.approx(0.6)
    assert provider.generation.max_tokens == 4096
    assert provider.generation.reasoning_effort == "medium"


def test_build_provider_uses_deepseek_backend_with_default_base() -> None:
    """DeepSeek provider 只填 apiKey 时也应落到官方默认地址。"""
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
                    "model": "deepseek-v4-flash",
                }
            },
        }
    )

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI"):
        provider = build_provider(config)

    assert provider.__class__.__name__ == "DeepSeekProvider"
    assert provider.get_default_model() == "deepseek-v4-flash"
    assert provider._spec is not None
    assert provider._spec.name == "deepseek"
    assert provider._effective_base == "https://api.deepseek.com"


def test_build_provider_uses_qwen_backend_with_default_base() -> None:
    """Qwen provider 只填 apiKey 时也应落到官方默认地址。"""
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
                    "model": "qwen-max",
                }
            },
        }
    )

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI"):
        provider = build_provider(config)

    assert provider.__class__.__name__ == "QwenProvider"
    assert provider.get_default_model() == "qwen-max"
    assert provider._spec is not None
    assert provider._spec.name == "qwen"
    assert provider._effective_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_build_provider_uses_zhipu_backend_with_default_base() -> None:
    """Zhipu provider 只填 apiKey 时也应落到官方默认地址。"""
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
                    "model": "glm-4.5",
                }
            },
        }
    )

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI"):
        provider = build_provider(config)

    assert provider.__class__.__name__ == "ZhipuProvider"
    assert provider.get_default_model() == "glm-4.5"
    assert provider._spec is not None
    assert provider._spec.name == "zhipu"
    assert provider._effective_base == "https://open.bigmodel.cn/api/paas/v4"


def test_build_provider_uses_minimax_anthropic_backend_with_default_base() -> None:
    """MiniMax provider 只填 apiKey 时应复用 Anthropic backend 并补默认地址。"""
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
                    "model": "MiniMax-M2.7",
                }
            },
        }
    )

    with patch("anthropic.AsyncAnthropic"):
        provider = build_provider(config)

    assert provider.__class__.__name__ == "AnthropicProvider"
    assert provider.get_default_model() == "MiniMax-M2.7"
    assert provider.api_base == "https://api.minimaxi.com/anthropic"


def test_build_provider_uses_moonshot_backend_with_default_base() -> None:
    """Moonshot provider 只填 apiKey 时应落到专用 backend 并补默认地址。"""
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
                    "model": "kimi-k2.6",
                }
            },
        }
    )

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI"):
        provider = build_provider(config)

    assert provider.__class__.__name__ == "MoonshotProvider"
    assert provider.get_default_model() == "kimi-k2.6"
    assert provider._spec is not None
    assert provider._spec.name == "moonshot"
    assert provider._effective_base == "https://api.moonshot.cn/v1"


def test_build_provider_uses_siliconflow_backend_with_default_base() -> None:
    """SiliconFlow provider 只填 apiKey 时应落到专用 backend 并补默认地址。"""
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
                    "model": "Pro/zai-org/GLM-4.7",
                }
            },
        }
    )

    with patch("nomi.providers.backends.openai_compat.AsyncOpenAI"):
        provider = build_provider(config)

    assert provider.__class__.__name__ == "SiliconFlowProvider"
    assert provider.get_default_model() == "Pro/zai-org/GLM-4.7"
    assert provider._spec is not None
    assert provider._spec.name == "siliconflow"
    assert provider._effective_base == "https://api.siliconflow.cn/v1"


def test_build_provider_rejects_unknown_forced_provider() -> None:
    """未知强制 provider 应立即报错。"""
    config = Config()
    config.agents.defaults.provider = "missing-provider"

    with pytest.raises(ValueError, match="Unknown provider configured: missing-provider"):
        build_provider(config)


def test_build_provider_rejects_missing_api_key_for_remote_provider() -> None:
    """远端 openai 兼容 provider 缺少 key 时应报错。"""
    config = Config()
    config.agents.defaults.provider = "openai"
    config.agents.defaults.model = "gpt-4o"

    with pytest.raises(ValueError, match="No API key configured for provider 'openai'"):
        build_provider(config)


def test_build_provider_rejects_missing_api_key_for_deepseek() -> None:
    """DeepSeek 缺少 apiKey 时应在装配阶段直接报错。"""
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                }
            }
        }
    )

    with pytest.raises(ValueError, match="No API key configured for provider 'deepseek'"):
        build_provider(config)


def test_build_provider_rejects_missing_api_key_for_qwen() -> None:
    """Qwen 缺少 apiKey 时应在装配阶段直接报错。"""
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "qwen",
                    "model": "qwen-max",
                }
            }
        }
    )

    with pytest.raises(ValueError, match="No API key configured for provider 'qwen'"):
        build_provider(config)


def test_build_provider_rejects_missing_api_key_for_zhipu() -> None:
    """Zhipu 缺少 apiKey 时应在装配阶段直接报错。"""
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "zhipu",
                    "model": "glm-4.5",
                }
            }
        }
    )

    with pytest.raises(ValueError, match="No API key configured for provider 'zhipu'"):
        build_provider(config)


def test_build_provider_rejects_missing_api_key_for_moonshot() -> None:
    """Moonshot 缺少 apiKey 时应在装配阶段直接报错。"""
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "moonshot",
                    "model": "kimi-k2.6",
                }
            }
        }
    )

    with pytest.raises(ValueError, match="No API key configured for provider 'moonshot'"):
        build_provider(config)


def test_build_provider_rejects_missing_api_key_for_siliconflow() -> None:
    """SiliconFlow 缺少 apiKey 时应在装配阶段直接报错。"""
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "siliconflow",
                    "model": "Pro/zai-org/GLM-4.7",
                }
            }
        }
    )

    with pytest.raises(ValueError, match="No API key configured for provider 'siliconflow'"):
        build_provider(config)


def test_build_provider_rejects_missing_api_key_for_minimax() -> None:
    """MiniMax 缺少 apiKey 时应在装配阶段直接报错。"""
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "minimax",
                    "model": "MiniMax-M2.7",
                }
            }
        }
    )

    with pytest.raises(ValueError, match="No API key configured for provider 'minimax'"):
        build_provider(config)
