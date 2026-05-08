"""onboard 向导主流程。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from nomi.cli.onboard.fields import (
    format_value,
    get_field_display_name,
    get_field_type_info,
    get_provider_names,
    summarize_model,
)
from nomi.cli.onboard.providers import (
    configure_single_provider,
    get_current_provider,
    input_context_window_with_recommendation,
    input_model_with_autocomplete,
    try_auto_fill_context_window,
)
from nomi.cli.onboard.types import OnboardResult
from nomi.cli.onboard.ui import (
    _BACK_PRESSED,
    console,
    get_questionary,
    input_bool,
    input_with_existing,
    print_summary_panel,
    select_with_back,
    show_config_panel,
    show_main_menu_header,
    show_section_header,
)
from nomi.config.loader import get_config_path, load_config
from nomi.config.schema import Config


_SELECT_FIELD_HINTS: dict[str, tuple[list[str], str]] = {
    "reasoning_effort": (
        ["low", "medium", "high"],
        "low / medium / high - enables LLM thinking mode",
    ),
}

_SETTINGS_SECTIONS: dict[str, tuple[str, str, set[str] | None]] = {
    "Agent Settings": ("Agent Defaults", "Configure default model, temperature, and behavior", None),
    "Tools": ("Tools Settings", "Configure web search, shell exec, and other tools", {"mcp_servers"}),
}

_SETTINGS_GETTER = {
    "Agent Settings": lambda c: c.agents.defaults,
    "Tools": lambda c: c.tools,
}

_SETTINGS_SETTER = {
    "Agent Settings": lambda c, v: setattr(c.agents, "defaults", v),
    "Tools": lambda c, v: setattr(c, "tools", v),
}


def _handle_model_field(
    working_model: BaseModel,
    field_name: str,
    field_display: str,
    current_value: Any,
) -> None:
    provider = get_current_provider(working_model)
    new_value = input_model_with_autocomplete(field_display, current_value, provider)
    if new_value is not None and new_value != current_value:
        setattr(working_model, field_name, new_value)
        try_auto_fill_context_window(working_model, new_value)


def _handle_context_window_field(
    working_model: BaseModel,
    field_name: str,
    field_display: str,
    current_value: Any,
) -> None:
    new_value = input_context_window_with_recommendation(
        field_display,
        current_value,
        working_model,
    )
    if new_value is not None:
        setattr(working_model, field_name, new_value)


_FIELD_HANDLERS: dict[str, Any] = {
    "model": _handle_model_field,
    "context_window_tokens": _handle_context_window_field,
}


def configure_pydantic_model(
    model: BaseModel,
    display_name: str,
    *,
    skip_fields: set[str] | None = None,
) -> BaseModel | None:
    """交互式编辑一个 Pydantic 模型。"""
    skip_fields = skip_fields or set()
    working_model = model.model_copy(deep=True)

    fields = [
        (name, info)
        for name, info in type(working_model).model_fields.items()
        if name not in skip_fields
    ]
    if not fields:
        console.print(f"[dim]{display_name}: No configurable fields[/dim]")
        return working_model

    def get_choices() -> list[str]:
        """返回当前配置块的可选字段列表。"""
        items = []
        for field_name, field_info in fields:
            value = getattr(working_model, field_name, None)
            display = get_field_display_name(field_name, field_info)
            formatted = format_value(value, rich=False, field_name=field_name)
            items.append(f"{display}: {formatted}")
        return items + ["[Done]"]

    while True:
        console.clear()
        show_config_panel(display_name, working_model, fields)
        choices = get_choices()
        answer = select_with_back("Select field to configure:", choices)

        if answer is _BACK_PRESSED or answer is None:
            return None
        if answer == "[Done]":
            return working_model

        field_idx = next((index for index, choice in enumerate(choices) if choice == answer), -1)
        if field_idx < 0 or field_idx >= len(fields):
            return None

        field_name, field_info = fields[field_idx]
        current_value = getattr(working_model, field_name, None)
        field_type = get_field_type_info(field_info)
        field_display = get_field_display_name(field_name, field_info)

        if field_type.type_name == "model":
            nested = current_value
            created = nested is None
            if nested is None and field_type.inner_type:
                nested = field_type.inner_type()
            if nested and isinstance(nested, BaseModel):
                updated = configure_pydantic_model(nested, field_display)
                if updated is not None:
                    setattr(working_model, field_name, updated)
                elif created:
                    setattr(working_model, field_name, None)
            continue

        handler = _FIELD_HANDLERS.get(field_name)
        if handler:
            handler(working_model, field_name, field_display, current_value)
            continue

        if field_name in _SELECT_FIELD_HINTS:
            choices_list, hint = _SELECT_FIELD_HINTS[field_name]
            select_choices = choices_list + ["(clear/unset)"]
            console.print(f"[dim]  Hint: {hint}[/dim]")
            new_value = select_with_back(
                field_display,
                select_choices,
                default=current_value or select_choices[0],
            )
            if new_value is _BACK_PRESSED:
                continue
            if new_value == "(clear/unset)":
                setattr(working_model, field_name, None)
            elif new_value is not None:
                setattr(working_model, field_name, new_value)
            continue

        if field_type.type_name == "bool":
            new_value = input_bool(field_display, current_value)
        else:
            new_value = input_with_existing(field_display, current_value, field_type.type_name)
        if new_value is not None:
            setattr(working_model, field_name, new_value)


def configure_providers(config: Config) -> None:
    """进入 provider 配置菜单。"""

    def get_provider_choices() -> list[str]:
        """返回 provider 菜单项列表。"""
        choices = []
        for name, display in get_provider_names().items():
            provider = getattr(config.providers, name, None)
            if provider and provider.api_key:
                choices.append(f"{display} *")
            else:
                choices.append(display)
        return choices + ["<- Back"]

    while True:
        try:
            console.clear()
            show_section_header("LLM Providers", "Select a provider to configure API key and endpoint")
            choices = get_provider_choices()
            answer = select_with_back("Select provider:", choices)

            if answer is _BACK_PRESSED or answer is None or answer == "<- Back":
                break

            assert isinstance(answer, str)
            provider_name = answer.replace(" *", "")
            for name, display in get_provider_names().items():
                if display == provider_name:
                    configure_single_provider(config, name)
                    break
        except KeyboardInterrupt:
            console.print("\n[dim]Returning to main menu...[/dim]")
            break


def configure_general_settings(config: Config, section: str) -> None:
    """配置 agent/tools 这类通用配置块。"""
    meta = _SETTINGS_SECTIONS.get(section)
    if not meta:
        return
    display_name, _subtitle, skip = meta
    model = _SETTINGS_GETTER[section](config)
    updated = configure_pydantic_model(model, display_name, skip_fields=skip)
    if updated is not None:
        _SETTINGS_SETTER[section](config, updated)


def show_summary(config: Config) -> None:
    """展示当前配置汇总。"""
    console.print()

    provider_rows = []
    for name, display in get_provider_names().items():
        provider = getattr(config.providers, name, None)
        status = "[green]configured[/green]" if (provider and provider.api_key) else "[dim]not configured[/dim]"
        provider_rows.append((display, status))
    print_summary_panel(provider_rows, "LLM Providers")

    for title, model in [
        ("Agent Settings", config.agents.defaults),
        ("Tools", config.tools),
    ]:
        print_summary_panel(summarize_model(model), title)


def has_unsaved_changes(original: Config, current: Config) -> bool:
    """判断当前会话是否有未保存改动。"""
    return original.model_dump(by_alias=True) != current.model_dump(by_alias=True)


def prompt_main_menu_exit(has_changes: bool) -> str:
    """决定主菜单退出方式。"""
    if not has_changes:
        return "discard"

    answer = get_questionary().select(
        "You have unsaved changes. What would you like to do?",
        choices=[
            "[S] Save and Exit",
            "[X] Exit Without Saving",
            "[R] Resume Editing",
        ],
        default="[R] Resume Editing",
        qmark=">",
    ).ask()

    if answer == "[S] Save and Exit":
        return "save"
    if answer == "[X] Exit Without Saving":
        return "discard"
    return "resume"


def run_onboard(initial_config: Config | None = None) -> OnboardResult:
    """运行交互式配置向导。"""
    get_questionary()

    if initial_config is not None:
        base_config = initial_config.model_copy(deep=True)
    else:
        config_path = get_config_path()
        if config_path.exists():
            base_config = load_config()
        else:
            base_config = Config()

    original_config = base_config.model_copy(deep=True)
    config = base_config.model_copy(deep=True)

    while True:
        console.clear()
        show_main_menu_header()

        try:
            answer = get_questionary().select(
                "What would you like to configure?",
                choices=[
                    "[P] LLM Provider",
                    "[A] Agent Settings",
                    "[T] Tools",
                    "[V] View Configuration Summary",
                    "[S] Save and Exit",
                    "[X] Exit Without Saving",
                ],
                qmark=">",
            ).ask()
        except KeyboardInterrupt:
            answer = None

        if answer is None:
            action = prompt_main_menu_exit(has_unsaved_changes(original_config, config))
            if action == "save":
                return OnboardResult(config=config, should_save=True)
            if action == "discard":
                return OnboardResult(config=original_config, should_save=False)
            continue

        menu_dispatch = {
            "[P] LLM Provider": lambda: configure_providers(config),
            "[A] Agent Settings": lambda: configure_general_settings(config, "Agent Settings"),
            "[T] Tools": lambda: configure_general_settings(config, "Tools"),
            "[V] View Configuration Summary": lambda: show_summary(config),
        }

        if answer == "[S] Save and Exit":
            return OnboardResult(config=config, should_save=True)
        if answer == "[X] Exit Without Saving":
            return OnboardResult(config=original_config, should_save=False)

        action_fn = menu_dispatch.get(answer)
        if action_fn:
            action_fn()
