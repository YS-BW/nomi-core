"""`nomi instance` 命令组。"""

from __future__ import annotations

import typer
from rich.table import Table

from nomi.cli.render import console
from nomi.cli.support.config import instance_option, instance_root_option, load_runtime_config
from nomi.cli.support.runtime_factory import make_runtime
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
from nomi.config.loader import get_config_path, save_config
from nomi.config.schema.instance import InstanceIdentityConfig
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

    @instance_app.command("invite-code")
    def invite_code(
        public_url: str | None = typer.Option(None, "--url", help="Public instance URL"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """生成当前实例的邀请信息。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        runtime = make_runtime(loaded_config)
        console.print(runtime.build_instance_invite_code(public_url))

    @instance_app.command("key")
    def instance_key(
        new_key: str | None = typer.Argument(None, help="New Nomi instance key"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """查看或设置当前实例对外 key。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        if new_key is None:
            console.print(loaded_config.instance.key)
            return
        loaded_config.instance.key = InstanceIdentityConfig(key=new_key).key
        save_config(loaded_config, get_config_path())
        console.print(f"[green]✓[/green] instance key 已更新为：{loaded_config.instance.key}")

    @instance_app.command("invite")
    def invite(
        from_code: str = typer.Option(..., "--from-code", help="Instance invite code"),
        permission: str = typer.Option("chat", "--permission", help="chat|task|all"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """向另一个实例发起好友申请。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        runtime = make_runtime(loaded_config)
        import asyncio

        result = asyncio.run(
            runtime.invite_instance(
                invite_code=from_code,
                requested_permission=permission,
            )
        )
        console.print(f"[green]✓[/green] 已向 {result.get('key') or '对方'} 发送好友申请")

    @instance_app.command("relations")
    def relations(
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """列出当前实例关系。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        runtime = make_runtime(loaded_config)
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Key", style="cyan", no_wrap=True)
        table.add_column("Name", style="white")
        table.add_column("Status", style="white")
        table.add_column("Direction", style="white")
        table.add_column("Permission", style="white")
        table.add_column("URL", style="white")
        for relation in runtime.list_instance_relations():
            table.add_row(
                relation["key"],
                relation.get("name") or "-",
                relation.get("status") or "-",
                relation.get("direction") or "-",
                relation.get("permission") or "-",
                relation.get("url") or "-",
            )
        console.print(table)

    @instance_app.command("accept")
    def accept(
        key: str,
        permission: str = typer.Option("chat", "--permission", help="chat|task|all"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """接受一条实例好友申请。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        runtime = make_runtime(loaded_config)
        import asyncio

        relation = asyncio.run(runtime.accept_instance_relation(key, permission))
        console.print(
            f"[green]✓[/green] 已接受 {relation['key']}，权限：{relation['permission']}"
        )

    @instance_app.command("reject")
    def reject(
        key: str,
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """拒绝一条实例好友申请。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        runtime = make_runtime(loaded_config)
        import asyncio

        asyncio.run(runtime.reject_instance_relation_async(key))
        console.print(f"[green]✓[/green] 已拒绝 {key}")

    @instance_app.command("rename")
    def rename(
        key: str,
        name: str,
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """更新实例关系备注。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        runtime = make_runtime(loaded_config)
        relation = runtime.rename_instance_relation(key, name)
        console.print(f"[green]✓[/green] 已把 {relation['key']} 备注为 {relation['name']}")

    @instance_app.command("remove-relation")
    def remove_relation(
        key: str,
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """删除一条实例好友关系。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        runtime = make_runtime(loaded_config)
        import asyncio

        asyncio.run(runtime.remove_instance_relation(key))
        console.print(f"[green]✓[/green] 已删除实例关系：{key}")

    @instance_app.command("permission")
    def permission(
        key: str,
        permission: str,
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """修改本地授予对方的权限。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        runtime = make_runtime(loaded_config)
        relation = runtime.set_instance_relation_permission(key, permission)
        console.print(
            f"[green]✓[/green] 已把 {relation['key']} 的权限设置为：{relation['permission']}"
        )

    @instance_app.command("send")
    def send(
        key: str,
        message: str,
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """向另一个实例发送消息。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        runtime = make_runtime(loaded_config)
        import asyncio

        result = asyncio.run(runtime.send_instance_message(key, message))
        console.print(result.get("content") or "")

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
