"""onboard 向导的交互与展示组件。"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import BaseModel
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nomi.cli.onboard.fields import format_value, get_field_display_name

console = Console()

_BACK_PRESSED = object()


def get_questionary():
    """返回 questionary；缺失时抛出明确错误。"""
    try:
        import questionary
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised in environments without wizard deps
        raise RuntimeError(
            "Interactive onboarding requires the optional 'questionary' dependency. "
            "Install project dependencies and rerun with --wizard."
        ) from exc
    return questionary


def select_with_back(
    prompt: str,
    choices: list[str],
    default: str | None = None,
) -> str | None | object:
    """支持返回上一步的选择框。"""
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    if not choices:
        logger.warning("Empty choices list provided to select_with_back")
        return None

    selected_index = 0
    if default and default in choices:
        selected_index = choices.index(default)

    state: dict[str, str | None | object] = {"result": None}

    def get_menu_text():
        """根据当前选中项生成菜单展示文本。"""
        items = []
        for index, choice in enumerate(choices):
            if index == selected_index:
                items.append(("class:selected", f"> {choice}\n"))
            else:
                items.append(("", f"  {choice}\n"))
        return items

    menu_control = FormattedTextControl(get_menu_text)
    menu_window = Window(content=menu_control, height=len(choices))

    prompt_control = FormattedTextControl(lambda: [("class:question", f"> {prompt}")])
    prompt_window = Window(content=prompt_control, height=1)
    layout = Layout(HSplit([prompt_window, menu_window]))

    bindings = KeyBindings()

    @bindings.add(Keys.Up)
    def _up(event):
        nonlocal selected_index
        selected_index = (selected_index - 1) % len(choices)
        event.app.invalidate()

    @bindings.add(Keys.Down)
    def _down(event):
        nonlocal selected_index
        selected_index = (selected_index + 1) % len(choices)
        event.app.invalidate()

    @bindings.add(Keys.Enter)
    def _enter(event):
        state["result"] = choices[selected_index]
        event.app.exit()

    @bindings.add("escape")
    def _escape(event):
        state["result"] = _BACK_PRESSED
        event.app.exit()

    @bindings.add(Keys.Left)
    def _left(event):
        state["result"] = _BACK_PRESSED
        event.app.exit()

    @bindings.add(Keys.ControlC)
    def _ctrl_c(event):
        state["result"] = None
        event.app.exit()

    style = Style.from_dict({
        "selected": "fg:green bold",
        "question": "fg:cyan",
    })

    app = Application(layout=layout, key_bindings=bindings, style=style)
    try:
        app.run()
    except Exception:
        logger.exception("Error in select prompt")
        return None

    return state["result"]


def show_config_panel(display_name: str, model: BaseModel, fields: list) -> None:
    """展示当前配置块。"""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="cyan")
    table.add_column("Value")

    for field_name, field_info in fields:
        value = getattr(model, field_name, None)
        display = get_field_display_name(field_name, field_info)
        formatted = format_value(value, rich=True, field_name=field_name)
        table.add_row(display, formatted)

    console.print(Panel(table, title=f"[bold]{display_name}[/bold]", border_style="blue"))


def show_main_menu_header() -> None:
    """展示主菜单头部。"""
    from rich.align import Align

    from nomi import __logo__, __version__

    console.print()
    console.print(Align.center(f"{__logo__} [bold cyan]nomi[{__version__}][/bold cyan]"))
    console.print()


def show_section_header(title: str, subtitle: str = "") -> None:
    """展示分区头部。"""
    console.print()
    if subtitle:
        console.print(
            Panel(f"[dim]{subtitle}[/dim]", title=f"[bold]{title}[/bold]", border_style="blue")
        )
    else:
        console.print(Panel("", title=f"[bold]{title}[/bold]", border_style="blue"))


def print_summary_panel(rows: list[tuple[str, str]], title: str) -> None:
    """打印简要汇总面板。"""
    if not rows:
        return
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Setting", style="cyan")
    table.add_column("Value")
    for field, value in rows:
        table.add_row(field, value)
    console.print(Panel(table, title=f"[bold]{title}[/bold]", border_style="blue"))


def input_bool(display_name: str, current: bool | None) -> bool | None:
    """获取布尔值输入。"""
    return get_questionary().confirm(
        display_name,
        default=bool(current) if current is not None else False,
    ).ask()


def input_text(display_name: str, current: Any, field_type: str) -> Any:
    """获取文本输入并按字段类型解析。"""
    from nomi.cli.onboard.fields import format_value_for_input

    default = format_value_for_input(current, field_type)
    value = get_questionary().text(f"{display_name}:", default=default).ask()

    if value is None or value == "":
        return None

    if field_type == "int":
        try:
            return int(value)
        except ValueError:
            console.print("[yellow]! Invalid number format, value not saved[/yellow]")
            return None
    if field_type == "float":
        try:
            return float(value)
        except ValueError:
            console.print("[yellow]! Invalid number format, value not saved[/yellow]")
            return None
    if field_type == "list":
        return [item.strip() for item in value.split(",") if item.strip()]
    if field_type == "dict":
        import json

        try:
            return json.loads(value)
        except json.JSONDecodeError:
            console.print("[yellow]! Invalid JSON format, value not saved[/yellow]")
            return None
    return value


def input_with_existing(display_name: str, current: Any, field_type: str) -> Any:
    """处理带保留现有值语义的输入。"""
    has_existing = current is not None and current != "" and current != {} and current != []
    if has_existing and not isinstance(current, list):
        choice = get_questionary().select(
            display_name,
            choices=["Enter new value", "Keep existing value"],
            default="Keep existing value",
        ).ask()
        if choice == "Keep existing value" or choice is None:
            return None
    return input_text(display_name, current, field_type)
