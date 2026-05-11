"""CLI 配置加载与工作区覆盖。"""

from __future__ import annotations

from pathlib import Path
from typing import TypeAlias

import typer

from nomi.cli.cli_error import exit_with_config_error
from nomi.cli.render import console
from nomi.config.instance import (
    DEFAULT_INSTANCE_NAME,
    InstanceContext,
    format_instance_name,
)
from nomi.config.loader import (
    configure_instance_context,
    get_config_path,
    load_config,
    resolve_config_env_vars,
    set_config_path,
)
from nomi.config.schema import Config

InstanceOption: TypeAlias = str | None


def instance_option() -> InstanceOption:
    """构造通用 `--instance` 参数。"""
    return typer.Option(
        None,
        "--instance",
        help=f"Instance name, defaults to `{DEFAULT_INSTANCE_NAME}`",
    )


def instance_root_option() -> InstanceOption:
    """构造通用 `--instance-root` 参数。"""
    return typer.Option(
        None,
        "--instance-root",
        help="Explicit instance root path",
    )


def resolve_runtime_instance(
    *,
    instance: str | None = None,
    instance_root: str | None = None,
    config: str | None = None,
    allow_missing_config: bool = False,
    silent: bool = False,
) -> InstanceContext:
    """解析并激活当前运行命令绑定的实例上下文。"""
    config_path = Path(config).expanduser().resolve() if config else None
    if config_path is not None and not config_path.exists() and not allow_missing_config:
        if not silent:
            console.print(f"[red]Error: Config file not found: {config_path}[/red]")
        raise typer.Exit(1)
    context = configure_instance_context(
        instance=instance,
        instance_root=instance_root,
        config_path=config_path,
    )
    if not silent:
        console.print(
            f"[dim]Using instance: {format_instance_name(context.name)} ({context.root})[/dim]"
        )
        if config_path is not None:
            console.print(f"[dim]Using config: {config_path}[/dim]")
    return context


def load_runtime_config(
    config: str | None = None,
    workspace: str | None = None,
    instance: str | None = None,
    instance_root: str | None = None,
    *,
    silent: bool = False,
) -> Config:
    """加载运行时配置，并按需覆盖当前工作区。"""
    resolve_runtime_instance(
        instance=instance,
        instance_root=instance_root,
        config=config,
        silent=silent,
    )
    config_path = Path(config).expanduser().resolve() if config else get_config_path()
    if config:
        set_config_path(Path(config).expanduser().resolve())
    elif not config_path.exists():
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
