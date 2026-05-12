"""`nomi remote` 配置命令组。"""

from __future__ import annotations

import secrets

import typer

from nomi.cli.render import console
from nomi.cli.support.config import instance_option, instance_root_option, load_runtime_config
from nomi.config.loader import get_config_path, save_config
from nomi.runtime.service.state import build_runtime_status_snapshot


def register_remote_command(app: typer.Typer) -> None:
    """注册 `remote` 命令组。"""
    remote_app = typer.Typer(help="Manage remote adapter configuration")

    @remote_app.callback(invoke_without_command=True)
    def remote_group(ctx: typer.Context) -> None:
        """处理 remote 命令组的空子命令场景。"""
        if ctx.invoked_subcommand is not None:
            return
        typer.echo(ctx.get_help())
        raise typer.Exit(0)

    @remote_app.command("enable")
    def enable(
        host: str | None = typer.Option(None, "--host", help="Remote listen host"),
        port: int | None = typer.Option(None, "--port", help="Remote listen port"),
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """启用 remote adapter 配置。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        loaded_config.remote.enabled = True
        if host is not None:
            loaded_config.remote.host = host
        if port is not None:
            loaded_config.remote.port = int(port)
        if not str(loaded_config.remote.auth_token or "").strip():
            loaded_config.remote.auth_token = _generate_remote_token()
        save_config(loaded_config, get_config_path())
        console.print("[green]✓[/green] remote adapter 已启用")
        console.print(f"host: {loaded_config.remote.host}")
        console.print(f"port: {loaded_config.remote.port}")
        console.print(f"token: {loaded_config.remote.auth_token}")
        console.print("运行 `nomi instance restart` 使配置生效。")

    @remote_app.command("disable")
    def disable(
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """禁用 remote adapter 配置。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        loaded_config.remote.enabled = False
        save_config(loaded_config, get_config_path())
        console.print("[green]✓[/green] remote adapter 已禁用")
        console.print("运行 `nomi instance restart` 使配置生效。")

    @remote_app.command("token")
    def token(
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """显示当前 remote token。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        current = str(loaded_config.remote.auth_token or "").strip()
        if not current:
            current = _generate_remote_token()
            loaded_config.remote.auth_token = current
            save_config(loaded_config, get_config_path())
        console.print(current)

    @remote_app.command("rotate-token")
    def rotate_token(
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """轮换 remote token。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        loaded_config.remote.auth_token = _generate_remote_token()
        save_config(loaded_config, get_config_path())
        console.print(loaded_config.remote.auth_token)
        console.print("运行 `nomi instance restart` 使新 token 生效。")

    @remote_app.command("status")
    def status(
        config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
    ) -> None:
        """显示 remote adapter 状态。"""
        loaded_config = load_runtime_config(
            config,
            None,
            instance=instance,
            instance_root=instance_root,
            silent=True,
        )
        snapshot = build_runtime_status_snapshot(loaded_config)
        console.print(f"enabled: {'yes' if snapshot.remote_enabled else 'no'}")
        console.print(f"running: {'yes' if snapshot.remote_running else 'no'}")
        console.print(f"host: {snapshot.remote_host}")
        console.print(f"port: {snapshot.remote_port}")
        console.print(f"runtime: {snapshot.service_state}")

    app.add_typer(remote_app, name="remote")


def _generate_remote_token() -> str:
    """生成 remote 访问 token。"""
    return f"nomi-remote-{secrets.token_hex(16)}"
