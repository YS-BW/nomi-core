"""提供方装配入口。"""

from __future__ import annotations

from nomi.config.schema import Config
from nomi.providers.base import GenerationSettings, LLMProvider
from nomi.providers.factory.resolution import resolve_provider


def build_provider(config: Config) -> LLMProvider:
    """按当前配置构建 provider。

    参数:
        config: 已完成环境变量展开和命令行覆盖的配置对象。

    返回:
        已实例化并注入默认生成参数的 provider。

    异常:
        ValueError: provider 配置非法或缺少必要凭证时抛出。
    """
    resolution = resolve_provider(config)
    model = resolution.model
    provider_name = resolution.provider_name
    provider_config = resolution.provider_config
    spec = resolution.spec
    backend = resolution.backend

    if backend == "azure_openai":
        if not provider_config or not provider_config.api_key or not provider_config.api_base:
            raise ValueError("Azure OpenAI requires api_key and api_base in config.")
    elif backend == "mimo":
        mimo_api_key = (
            (getattr(provider_config, "token_plan_api_key", "") or provider_config.api_key)
            if provider_config
            else ""
        )
        if not mimo_api_key:
            raise ValueError("No API key configured for provider 'mimo'.")
    elif backend == "deepseek":
        if not provider_config or not provider_config.api_key:
            raise ValueError("No API key configured for provider 'deepseek'.")
    elif backend == "qwen":
        if not provider_config or not provider_config.api_key:
            raise ValueError("No API key configured for provider 'qwen'.")
    elif backend == "zhipu":
        if not provider_config or not provider_config.api_key:
            raise ValueError("No API key configured for provider 'zhipu'.")
    elif backend == "moonshot":
        if not provider_config or not provider_config.api_key:
            raise ValueError("No API key configured for provider 'moonshot'.")
    elif backend == "siliconflow":
        if not provider_config or not provider_config.api_key:
            raise ValueError("No API key configured for provider 'siliconflow'.")
    elif provider_name == "minimax":
        if not provider_config or not provider_config.api_key:
            raise ValueError("No API key configured for provider 'minimax'.")
    elif backend == "openai_compat" and not model.startswith("bedrock/"):
        needs_key = not (provider_config and provider_config.api_key)
        exempt = spec and (spec.is_local or spec.is_direct)
        if needs_key and not exempt:
            raise ValueError(f"No API key configured for provider '{provider_name}'.")

    if backend == "azure_openai":
        from nomi.providers.backends.azure_openai import AzureOpenAIProvider

        provider = AzureOpenAIProvider(
            api_key=provider_config.api_key,
            api_base=provider_config.api_base,
            default_model=model,
        )
    elif backend == "anthropic":
        from nomi.providers.backends.anthropic import AnthropicProvider

        provider: LLMProvider = AnthropicProvider(
            api_key=provider_config.api_key if provider_config else None,
            api_base=resolution.api_base,
            default_model=model,
            extra_headers=provider_config.extra_headers if provider_config else None,
        )
    elif backend == "mimo":
        from nomi.providers.backends.mimo import MiMoProvider

        mimo_api_key = getattr(provider_config, "token_plan_api_key", "") or provider_config.api_key
        provider = MiMoProvider(
            api_key=mimo_api_key if provider_config else None,
            api_base=resolution.api_base,
            default_model=model,
            extra_headers=provider_config.extra_headers if provider_config else None,
            spec=spec,
        )
    elif backend == "deepseek":
        from nomi.providers.backends.deepseek import DeepSeekProvider

        provider = DeepSeekProvider(
            api_key=provider_config.api_key if provider_config else None,
            api_base=resolution.api_base,
            default_model=model,
            extra_headers=provider_config.extra_headers if provider_config else None,
            spec=spec,
        )
    elif backend == "qwen":
        from nomi.providers.backends.qwen import QwenProvider

        provider = QwenProvider(
            api_key=provider_config.api_key if provider_config else None,
            api_base=resolution.api_base,
            default_model=model,
            extra_headers=provider_config.extra_headers if provider_config else None,
            spec=spec,
        )
    elif backend == "zhipu":
        from nomi.providers.backends.zhipu import ZhipuProvider

        provider = ZhipuProvider(
            api_key=provider_config.api_key if provider_config else None,
            api_base=resolution.api_base,
            default_model=model,
            extra_headers=provider_config.extra_headers if provider_config else None,
            spec=spec,
        )
    elif backend == "moonshot":
        from nomi.providers.backends.moonshot import MoonshotProvider

        provider = MoonshotProvider(
            api_key=provider_config.api_key if provider_config else None,
            api_base=resolution.api_base,
            default_model=model,
            extra_headers=provider_config.extra_headers if provider_config else None,
            spec=spec,
        )
    elif backend == "siliconflow":
        from nomi.providers.backends.siliconflow import SiliconFlowProvider

        provider = SiliconFlowProvider(
            api_key=provider_config.api_key if provider_config else None,
            api_base=resolution.api_base,
            default_model=model,
            extra_headers=provider_config.extra_headers if provider_config else None,
            spec=spec,
        )
    else:
        from nomi.providers.backends.openai_compat import OpenAICompatProvider

        provider = OpenAICompatProvider(
            api_key=provider_config.api_key if provider_config else None,
            api_base=resolution.api_base,
            default_model=model,
            extra_headers=provider_config.extra_headers if provider_config else None,
            spec=spec,
        )

    defaults = config.agents.defaults
    provider.generation = GenerationSettings(
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        reasoning_effort=defaults.reasoning_effort,
    )
    return provider
