"""`nomi channel` 命令组。"""

from __future__ import annotations

import typer
from loguru import logger

from nomi.channel.registry import get_active_channel_kind
from nomi.channel.service.state import validate_active_channel_enabled
from nomi.channel.service.usecases import (
    login_active_channel,
    restart_channel_service,
    run_channel_foreground,
    serve_channel_internal,
    start_channel_service,
    stop_channel_service,
    tail_channel_service_log,
)
from nomi.cli.support.config import load_runtime_config
from nomi.cli.support.runtime_factory import make_runtime
from nomi.utils.workspace import sync_workspace_templates


def register_channel_command(app: typer.Typer) -> None:
    """注册 `channel` 命令组。"""
    channel_app = typer.Typer(help="Manage external channel service")

    @channel_app.callback(invoke_without_command=True)
    def channel_group(ctx: typer.Context) -> None:
        """处理 channel 命令组的空子命令场景。"""
        if ctx.invoked_subcommand is not None:
            return
        typer.echo(ctx.get_help())
        raise typer.Exit(0)

    @channel_app.command("login")
    def login(
        force: bool = typer.Option(False, "--force", "-f", help="Force re-authentication"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    ) -> None:
        """执行当前启用 channel 的交互式登录。"""
        loaded_config = load_runtime_config(config, None, silent=True)
        kind = get_active_channel_kind(loaded_config)
        if not kind:
            raise typer.BadParameter(
                "当前未启用任何 channel。\n请先在配置中设置 `channel.kind`。"
            )
        validate_active_channel_enabled(loaded_config)
        success = login_active_channel(loaded_config, force=force)
        if not success:
            raise typer.Exit(1)

    @channel_app.command("run")
    def run(
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    ) -> None:
        """以前台方式运行当前启用的 channel，并默认打印日志。"""
        loaded_config = load_runtime_config(config, workspace, silent=True)
        sync_workspace_templates(loaded_config.workspace_path, silent=True)
        logger.enable("nomi")
        run_channel_foreground(loaded_config, make_runtime)

    @channel_app.command("_serve_internal", hidden=True)
    def serve_internal(
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    ) -> None:
        """后台 service 专用入口，绕过外层互斥检查。"""
        loaded_config = load_runtime_config(config, workspace, silent=True)
        sync_workspace_templates(loaded_config.workspace_path, silent=True)
        logger.enable("nomi")
        serve_channel_internal(loaded_config, make_runtime)

    @channel_app.command("start")
    def start(
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    ) -> None:
        """后台启动当前启用的 channel service。"""
        loaded_config = load_runtime_config(config, workspace, silent=True)
        start_channel_service(config, workspace, loaded_config)

    @channel_app.command("log")
    def log() -> None:
        """实时展示后台 channel service 日志，Ctrl+C 退出但不影响后台。"""
        tail_channel_service_log()

    @channel_app.command("stop")
    def stop() -> None:
        """停止后台 channel service。"""
        stop_channel_service()

    @channel_app.command("restart")
    def restart(
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    ) -> None:
        """重启后台 channel service；未运行时则直接启动。"""
        loaded_config = load_runtime_config(config, workspace, silent=True)
        restart_channel_service(config, workspace, loaded_config)

    app.add_typer(channel_app, name="channel")
