"""`nomi instance` 命令组。"""

from __future__ import annotations

import typer
from rich.table import Table

from nomi.cli.render import console
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
        """汇总所有实例的 channel/remote 服务状态。"""
        rows = build_instance_service_rows()
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Instance", style="cyan", no_wrap=True)
        table.add_column("Root", style="white")
        table.add_column("Channel", style="white")
        table.add_column("Remote", style="white")
        table.add_column("Port", style="white")
        table.add_column("Login", style="white")
        table.add_column("Logs", style="white")
        for row in rows:
            table.add_row(
                row["instance"],
                row["root"],
                row["channel"],
                row["remote"],
                row["port"],
                row["login"],
                row["logs"],
            )
        console.print(table)

    app.add_typer(instance_app, name="instance")
