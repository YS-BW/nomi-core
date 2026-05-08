"""CLI 配置加载与工作区覆盖。"""

from __future__ import annotations

from pathlib import Path

import typer

from nomi.cli.cli_error import exit_with_config_error
from nomi.cli.render import console
from nomi.config.loader import (
    get_config_path,
    load_config,
    resolve_config_env_vars,
    set_config_path,
)
from nomi.config.schema import Config


def load_runtime_config(
    config: str | None = None,
    workspace: str | None = None,
    *,
    silent: bool = False,
) -> Config:
    """加载运行时配置，并按需覆盖当前工作区。"""
    config_path = None
    if config:
        config_path = Path(config).expanduser().resolve()
        if not config_path.exists():
            if not silent:
                console.print(f"[red]Error: Config file not found: {config_path}[/red]")
            raise typer.Exit(1)
        set_config_path(config_path)
        if not silent:
            console.print(f"[dim]Using config: {config_path}[/dim]")
    else:
        default_config_path = get_config_path()
        if not default_config_path.exists():
            console.print(
                "[yellow]未找到配置文件，当前将使用默认内存配置运行。"
                "建议先运行 `nomi onboard` 完成初始化。[/yellow]"
            )

    try:
        loaded = resolve_config_env_vars(load_config(config_path))
    except ValueError as exc:
        if not silent:
            raise exit_with_config_error(str(exc))
        raise typer.Exit(1) from exc

    if workspace:
        loaded.agents.defaults.workspace = workspace
    return loaded
