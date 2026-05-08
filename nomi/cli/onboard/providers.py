"""onboard 向导里的 provider / 模型输入辅助。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from nomi.cli.onboard.fields import get_provider_info
from nomi.cli.onboard.ui import console, get_questionary
from nomi.providers.factory.model_catalog import (
    format_token_count,
    get_model_context_limit,
    get_model_suggestions,
)


def get_current_provider(model: BaseModel) -> str:
    """从模型对象中读取当前 provider。"""
    if hasattr(model, "provider"):
        return getattr(model, "provider", "auto") or "auto"
    return "auto"


def input_model_with_autocomplete(
    display_name: str,
    current: Any,
    provider: str,
) -> str | None:
    """带动态补全的模型输入框。"""
    from prompt_toolkit.completion import Completer, Completion

    default = str(current) if current else ""

    class DynamicModelCompleter(Completer):
        """动态拉取模型候选项的补全器。"""

        def __init__(self, provider_name: str):
            """记录当前补全器绑定的 provider 名称。"""
            self.provider = provider_name

        def get_completions(self, document, complete_event):
            """根据当前输入动态产出模型候选项。"""
            del complete_event
            text = document.text_before_cursor
            suggestions = get_model_suggestions(text, provider=self.provider, limit=50)
            for model in suggestions:
                if text.lower() not in model.lower():
                    continue
                yield Completion(
                    model,
                    start_position=-len(text),
                    display=model,
                )

    value = get_questionary().autocomplete(
        f"{display_name}:",
        choices=[""],
        completer=DynamicModelCompleter(provider),
        default=default,
        qmark=">",
    ).ask()
    return value if value else None


def input_context_window_with_recommendation(
    display_name: str,
    current: Any,
    model_obj: BaseModel,
) -> int | None:
    """输入上下文窗口，并支持自动推荐。"""
    current_val = current if current else ""

    choices = ["Enter new value"]
    if current_val:
        choices.append("Keep existing value")
    choices.append("[?] Get recommended value")

    choice = get_questionary().select(
        display_name,
        choices=choices,
        default="Enter new value",
    ).ask()

    if choice is None:
        return None
    if choice == "Keep existing value":
        return None
    if choice == "[?] Get recommended value":
        model_name = getattr(model_obj, "model", None)
        if not model_name:
            console.print("[yellow]! Please configure the model field first[/yellow]")
            return None

        provider = get_current_provider(model_obj)
        context_limit = get_model_context_limit(model_name, provider)
        if context_limit:
            console.print(
                f"[green]+ Recommended context window: {format_token_count(context_limit)} tokens[/green]"
            )
            return context_limit
        console.print("[yellow]! Could not fetch model info, please enter manually[/yellow]")

    value = get_questionary().text(
        f"{display_name}:",
        default=str(current_val) if current_val else "",
    ).ask()
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        console.print("[yellow]! Invalid number format, value not saved[/yellow]")
        return None


def try_auto_fill_context_window(model: BaseModel, new_model_name: str) -> None:
    """在上下文窗口仍是默认值时尝试自动填充。"""
    if not hasattr(model, "context_window_tokens"):
        return

    current_context = getattr(model, "context_window_tokens", None)

    from nomi.config.schema import AgentDefaults

    default_context = AgentDefaults.model_fields["context_window_tokens"].default
    if current_context != default_context:
        return

    provider = get_current_provider(model)
    context_limit = get_model_context_limit(new_model_name, provider)
    if context_limit:
        setattr(model, "context_window_tokens", context_limit)
        console.print(
            f"[green]+ Auto-filled context window: {format_token_count(context_limit)} tokens[/green]"
        )
    else:
        console.print("[dim](i) Could not auto-fill context window (model not in database)[/dim]")


def configure_single_provider(config, provider_name: str) -> None:
    """配置单个 provider。"""
    from nomi.cli.onboard.flow import configure_pydantic_model
    from nomi.cli.onboard.fields import get_provider_names

    provider_config = getattr(config.providers, provider_name, None)
    if provider_config is None:
        console.print(f"[red]Unknown provider: {provider_name}[/red]")
        return

    display_name = get_provider_names().get(provider_name, provider_name)
    default_api_base = get_provider_info().get(provider_name, (None, None, None, None))[3]
    if default_api_base and not provider_config.api_base:
        provider_config.api_base = default_api_base

    updated_provider = configure_pydantic_model(provider_config, display_name)
    if updated_provider is not None:
        setattr(config.providers, provider_name, updated_provider)
