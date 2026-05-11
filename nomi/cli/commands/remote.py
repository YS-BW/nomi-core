"""`nomi remote` 命令组。"""

from __future__ import annotations

import typer
from loguru import logger

from nomi.cli.support.config import load_runtime_config
from nomi.cli.support.config import instance_option, instance_root_option
from nomi.cli.support.runtime_factory import make_runtime
from nomi.remote.service.usecases import (
    restart_remote_service,
    run_remote_service_foreground,
    serve_remote_internal,
    start_remote_service,
    stop_remote_service,
    tail_remote_service_log,
)
from nomi.utils.workspace import sync_workspace_templates


def register_remote_command(app: typer.Typer) -> None:
    """注册 `remote` 命令组。"""
    remote_app = typer.Typer(help="Manage remote desktop shell service")

    @remote_app.callback(invoke_without_command=True)
    def remote_group(ctx: typer.Context) -> None:
        """处理 remote 命令组的空子命令场景。"""
        if ctx.invoked_subcommand is not None:
            return
        typer.echo(ctx.get_help())
        raise typer.Exit(0)

    @remote_app.command("run")
    def run(
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """以前台方式运行 remote service。"""
        loaded_config = load_runtime_config(
            config,
            workspace,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        sync_workspace_templates(loaded_config.workspace_path, silent=True)
        logger.enable("nomi")
        run_remote_service_foreground(loaded_config, make_runtime)

    @remote_app.command("_serve_internal", hidden=True)
    def serve_internal(
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """后台 service 专用入口。"""
        loaded_config = load_runtime_config(
            config,
            workspace,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        sync_workspace_templates(loaded_config.workspace_path, silent=True)
        logger.enable("nomi")
        serve_remote_internal(loaded_config, make_runtime)

    @remote_app.command("start")
    def start(
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """后台启动 remote service。"""
        loaded_config = load_runtime_config(
            config,
            workspace,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        start_remote_service(config, workspace, loaded_config, instance=instance, instance_root=instance_root)

    @remote_app.command("log")
    def log(
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    ) -> None:
        """实时展示后台 remote service 日志。"""
        load_runtime_config(config, None, instance=instance, instance_root=instance_root, silent=True)
        tail_remote_service_log()

    @remote_app.command("stop")
    def stop(
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    ) -> None:
        """停止后台 remote service。"""
        loaded_config = load_runtime_config(config, None, instance=instance, instance_root=instance_root, silent=True)
        stop_remote_service(loaded_config)

    @remote_app.command("restart")
    def restart(
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """重启后台 remote service。"""
        loaded_config = load_runtime_config(
            config,
            workspace,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        restart_remote_service(
            config,
            workspace,
            loaded_config,
            instance=instance,
            instance_root=instance_root,
        )

    app.add_typer(remote_app, name="remote")
