"""`nomi channel` 配置命令组。"""

from __future__ import annotations

from typing import Literal

import typer

from nomi.channel.registry import channel_has_login_state, get_active_channel_kind, get_channel_spec
from nomi.channel.service.usecases import login_active_channel
from nomi.cli.render import console
from nomi.cli.support.config import (
    instance_option,
    instance_root_option,
    load_runtime_config,
)
from nomi.config.loader import get_config_path, save_config
from nomi.runtime.service.state import build_runtime_status_snapshot


def register_channel_command(app: typer.Typer) -> None:
    """注册 `channel` 命令组。"""
    channel_app = typer.Typer(help="Manage external channel adapter configuration")

    @channel_app.callback(invoke_without_command=True)
    def channel_group(ctx: typer.Context) -> None:
        """处理 channel 命令组的空子命令场景。"""
        if ctx.invoked_subcommand is not None:
            return
        typer.echo(ctx.get_help())
        raise typer.Exit(0)

    @channel_app.command("enable")
    def enable(
        kind: Literal["weixin"] = typer.Argument(..., help="Channel kind"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """启用指定 channel adapter 配置。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        get_channel_spec(kind)
        loaded_config.channel.kind = kind
        save_config(loaded_config, get_config_path())
        console.print(f"[green]✓[/green] channel adapter 已启用：{kind}")
        console.print("运行 `nomi instance restart` 使配置生效。")

    @channel_app.command("disable")
    def disable(
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """禁用当前 channel adapter 配置。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        loaded_config.channel.kind = ""
        save_config(loaded_config, get_config_path())
        console.print("[green]✓[/green] channel adapter 已禁用")
        console.print("运行 `nomi instance restart` 使配置生效。")

    @channel_app.command("login")
    def login(
        force: bool = typer.Option(False, "--force", "-f", help="Force re-authentication"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """执行当前启用 channel 的交互式登录。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        kind = get_active_channel_kind(loaded_config)
        if not kind:
            raise typer.BadParameter(
                "当前未启用任何 channel。\n请先运行：nomi channel enable weixin"
            )
        success = login_active_channel(loaded_config, force=force)
        if not success:
            raise typer.Exit(1)

    @channel_app.command("status")
    def status(
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """显示 channel adapter 状态。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        snapshot = build_runtime_status_snapshot(loaded_config)
        kind = snapshot.channel_kind or "-"
        logged_in = channel_has_login_state(loaded_config, kind) if kind != "-" else False
        console.print(f"enabled: {'yes' if snapshot.channel_enabled else 'no'}")
        console.print(f"kind: {kind}")
        console.print(f"logged_in: {'yes' if logged_in else 'no'}")
        console.print(f"running: {'yes' if snapshot.channel_running else 'no'}")
        console.print(f"runtime: {snapshot.service_state}")

    app.add_typer(channel_app, name="channel")
