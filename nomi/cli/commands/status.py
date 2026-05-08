"""status 命令。"""

from __future__ import annotations

import typer
from rich.table import Table

from nomi import __logo__
from nomi.cli.render import console
from nomi.cli.support.status import build_status_rows


def register_status_command(app: typer.Typer) -> None:
    """注册 status 命令。

    参数:
        app: 根 `Typer` 应用实例。

    返回:
        无返回值。
    """

    @app.command()
    def status() -> None:
        """显示 Nomi 当前状态。

        返回:
            无返回值。
        """
        console.print(f"{__logo__} nomi Status\n")
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("字段", style="cyan", no_wrap=True)
        table.add_column("当前值", style="white")
        table.add_column("说明", style="white")
        for row in build_status_rows():
            table.add_row(row.key, row.value, row.description)
        console.print(table)
