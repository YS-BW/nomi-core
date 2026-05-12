"""`nomi instance` 命令组。"""

from __future__ import annotations

import typer
from rich.table import Table

from nomi.cli.render import console
from nomi.cli.support.config import instance_option, instance_root_option
from nomi.cli.support.config import load_runtime_config
from nomi.cli.support.status import (
    build_instance_service_rows,
    format_home_path,
)
from nomi.config.instance import (
    DEFAULT_INSTANCE_NAME,
    ensure_instance_layout,
    format_instance_name,
    list_instance_contexts,
    lookup_instance_context,
    register_instance,
    remove_instance_root,
    remove_registered_instance,
)
from nomi.cli.support.runtime_factory import make_runtime
from nomi.runtime.service.runner import (
    follow_log_file,
    restart_background_service,
    run_foreground_service,
    start_background_service,
    stop_background_service,
)
from nomi.runtime.service.state import get_service_log_path
from nomi.utils.workspace import sync_workspace_templates


def register_instance_command(app: typer.Typer) -> None:
    """注册 `instance` 命令组。"""
    instance_app = typer.Typer(help="Manage nomi instances")

    @instance_app.callback(invoke_without_command=True)
    def instance_group(ctx: typer.Context) -> None:
        """处理空子命令场景。"""
        if ctx.invoked_subcommand is not None:
            return
        typer.echo(ctx.get_help())
        raise typer.Exit(0)

    @instance_app.command("list")
    def list_instances() -> None:
        """列出默认实例与已注册实例。"""
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Instance", style="cyan", no_wrap=True)
        table.add_column("Root", style="white")
        table.add_column("Registered", style="white")
        for context in list_instance_contexts():
            table.add_row(
                format_instance_name(context.name),
                format_home_path(context.root),
                "yes" if context.name == DEFAULT_INSTANCE_NAME or context.name else "no",
            )
        console.print(table)

    @instance_app.command("create")
    def create_instance(name: str) -> None:
        """创建一条命名实例及其标准目录。"""
        context = register_instance(name)
        ensure_instance_layout(context.root)
        console.print(f"[green]✓[/green] 已创建实例：{context.name}")
        console.print(f"root: {context.root}")

    @instance_app.command("inspect")
    def inspect_instance(name: str) -> None:
        """查看一条实例的关键信息。"""
        context = lookup_instance_context(name)
        ensure_instance_layout(context.root)
        console.print(f"instance: {format_instance_name(context.name)}")
        console.print(f"root: {context.root}")
        console.print(f"config: {context.config_path}")
        for entry in ("workspace", "logs", "skills", "history", "media", "sessions"):
            console.print(f"{entry}: {context.root / entry}")

    @instance_app.command("remove")
    def remove_instance(name: str) -> None:
        """删除一条命名实例。"""
        context = remove_registered_instance(name)
        remove_instance_root(context.root)
        console.print(f"[green]✓[/green] 已删除实例：{context.name}")

    @instance_app.command("services")
    def services() -> None:
        """汇总所有实例的 runtime 与 adapter 状态。"""
        rows = build_instance_service_rows()
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Instance", style="cyan", no_wrap=True)
        table.add_column("Root", style="white")
        table.add_column("Runtime", style="white")
        table.add_column("Scheduler", style="white")
        table.add_column("Remote", style="white")
        table.add_column("Channel", style="white")
        table.add_column("Port", style="white")
        table.add_column("Login", style="white")
        table.add_column("Logs", style="white")
        for row in rows:
            table.add_row(
                row["instance"],
                row["root"],
                row["runtime"],
                row["scheduler"],
                row["remote"],
                row["channel"],
                row["port"],
                row["login"],
                row["logs"],
            )
        console.print(table)

    @instance_app.command("run")
    def run(
        name: str | None = typer.Argument(None, help="Instance name"),
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """以前台方式运行唯一实例 runtime。"""
        resolved_instance = instance or name
        loaded_config = load_runtime_config(
            config,
            workspace,
            instance=resolved_instance,
            instance_root=instance_root,
            silent=True,
        )
        sync_workspace_templates(loaded_config.workspace_path, silent=True)
        run_foreground_service(loaded_config, make_runtime)

    @instance_app.command("_serve_internal", hidden=True)
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
        run_foreground_service(loaded_config, make_runtime)

    @instance_app.command("start")
    def start(
        name: str | None = typer.Argument(None, help="Instance name"),
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """后台启动唯一实例 runtime。"""
        resolved_instance = instance or name
        loaded_config = load_runtime_config(
            config,
            workspace,
            instance=resolved_instance,
            instance_root=instance_root,
            silent=True,
        )
        sync_workspace_templates(loaded_config.workspace_path, silent=True)
        start_background_service(
            config,
            workspace,
            loaded_config,
            instance=resolved_instance,
            instance_root=instance_root,
        )

    @instance_app.command("stop")
    def stop(
        name: str | None = typer.Argument(None, help="Instance name"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """停止唯一实例 runtime。"""
        resolved_instance = instance or name
        loaded_config = load_runtime_config(
            config,
            None,
            instance=resolved_instance,
            instance_root=instance_root,
            silent=True,
        )
        stop_background_service(loaded_config)

    @instance_app.command("restart")
    def restart(
        name: str | None = typer.Argument(None, help="Instance name"),
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """重启唯一实例 runtime。"""
        resolved_instance = instance or name
        loaded_config = load_runtime_config(
            config,
            workspace,
            instance=resolved_instance,
            instance_root=instance_root,
            silent=True,
        )
        sync_workspace_templates(loaded_config.workspace_path, silent=True)
        restart_background_service(
            config,
            workspace,
            loaded_config,
            instance=resolved_instance,
            instance_root=instance_root,
        )

    @instance_app.command("log")
    def log(
        name: str | None = typer.Argument(None, help="Instance name"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """实时展示唯一实例 runtime 日志。"""
        resolved_instance = instance or name
        load_runtime_config(
            config,
            None,
            instance=resolved_instance,
            instance_root=instance_root,
            silent=True,
        )
        follow_log_file(get_service_log_path())

    @instance_app.command("status")
    def status(
        name: str | None = typer.Argument(None, help="Instance name"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """显示指定实例 runtime 状态。"""
        from nomi.cli.support.status import build_status_rows

        resolved_instance = instance or name
        for row in build_status_rows(
            config=config,
            instance=resolved_instance,
            instance_root=instance_root,
        ):
            console.print(f"{row.key}: {row.value}")

    app.add_typer(instance_app, name="instance")
