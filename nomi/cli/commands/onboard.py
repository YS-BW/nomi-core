"""onboard 命令。"""

from __future__ import annotations

from pathlib import Path

import typer

from nomi import __logo__
from nomi.cli.render import console
from nomi.cli.support.config import instance_option, instance_root_option, resolve_runtime_instance
from nomi.config.instance import DEFAULT_INSTANCE_NAME, ensure_instance_layout, register_instance
from nomi.config.paths import get_workspace_path
from nomi.config.schema import Config
from nomi.utils.workspace import sync_workspace_templates


def register_onboard_command(app: typer.Typer) -> None:
    """注册 onboard 命令。

    参数:
        app: 根 `Typer` 应用实例。

    返回:
        无返回值。
    """

    @app.command()
    def onboard(
        workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
        config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
        instance: str | None = instance_option(),
        instance_root: str | None = instance_root_option(),
        wizard: bool = typer.Option(False, "--wizard", help="Use interactive wizard"),
    ) -> None:
        """初始化配置文件与工作区。

        参数:
            workspace: 覆盖默认工作区目录。
            config: 指定配置文件路径。
            wizard: 是否启用交互式向导。

        返回:
            无返回值。
        """
        from nomi.config.loader import (
            get_config_path,
            load_config,
            save_config,
            set_config_path,
        )

        context = resolve_runtime_instance(
            instance=instance,
            instance_root=instance_root,
            config=config,
            allow_missing_config=True,
        )
        ensure_instance_layout(context.root)
        if context.name and context.name != DEFAULT_INSTANCE_NAME:
            register_instance(context.name, context.root)
        if config:
            config_path = Path(config).expanduser().resolve()
            set_config_path(config_path)
        else:
            config_path = get_config_path()
        console.print(f"[dim]实例：{context.name or '(unregistered)'}[/dim]")
        console.print(f"[dim]实例 root：{context.root}[/dim]")

        def _apply_workspace_override(loaded: Config) -> Config:
            if workspace:
                loaded.agents.defaults.workspace = workspace
            return loaded

        if config_path.exists():
            if wizard:
                loaded_config = _apply_workspace_override(load_config(config_path))
            else:
                console.print(f"[yellow]配置文件已存在：{config_path}[/yellow]")
                console.print(
                    "  [bold]y[/bold] = 用默认值覆盖（会丢失现有配置）"
                )
                console.print(
                    "  [bold]N[/bold] = 刷新配置，保留现有值并补齐新字段"
                )
                if typer.confirm("是否覆盖？"):
                    loaded_config = _apply_workspace_override(Config())
                    save_config(loaded_config, config_path)
                    console.print(
                        f"[green]✓[/green] 已将配置重置为默认值：{config_path}"
                    )
                else:
                    loaded_config = _apply_workspace_override(load_config(config_path))
                    save_config(loaded_config, config_path)
                    console.print(
                        f"[green]✓[/green] 已刷新配置并保留现有值：{config_path}"
                    )
        else:
            loaded_config = _apply_workspace_override(Config())
            if not wizard:
                save_config(loaded_config, config_path)
                console.print(f"[green]✓[/green] 已创建配置文件：{config_path}")

        if wizard:
            from nomi.cli.onboard import run_onboard

            try:
                result = run_onboard(initial_config=loaded_config)
                if not result.should_save:
                    console.print("[yellow]已放弃本次配置，未保存任何变更。[/yellow]")
                    return

                loaded_config = result.config
                save_config(loaded_config, config_path)
                console.print(f"[green]✓[/green] 已保存配置文件：{config_path}")
            except Exception as exc:
                console.print(f"[red]✗[/red] 配置过程中出错：{exc}")
                console.print("[yellow]请重新运行 `nomi onboard` 完成初始化。[/yellow]")
                raise typer.Exit(1)

        workspace_path = get_workspace_path(loaded_config.workspace_path)
        if not workspace_path.exists():
            workspace_path.mkdir(parents=True, exist_ok=True)
            console.print(f"[green]✓[/green] 已创建工作区：{workspace_path}")

        sync_workspace_templates(workspace_path)

        agent_cmd = 'nomi agent -m "你好！"'
        if instance_root:
            agent_cmd += f" --instance-root {context.root}"
        elif context.name and context.name != DEFAULT_INSTANCE_NAME:
            agent_cmd += f" --instance {context.name}"
        elif config:
            agent_cmd += f" --config {config_path}"

        console.print(f"\n{__logo__} nomi 已就绪！")
        console.print("\n下一步：")
        if wizard:
            console.print(f"  1. 开始对话：[cyan]{agent_cmd}[/cyan]")
        else:
            console.print(f"  1. 把 API Key 填到 [cyan]{config_path}[/cyan]")
            console.print("     获取地址：https://platform.xiaomimimo.com/console/api-keys")
            console.print(f"  2. 开始对话：[cyan]{agent_cmd}[/cyan]")
