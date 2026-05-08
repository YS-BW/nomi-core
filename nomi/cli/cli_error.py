"""CLI 用户态错误转译。"""

from __future__ import annotations

import typer

from nomi.cli.render import console


def exit_with_config_error(message: str) -> typer.Exit:
    """输出配置相关用户错误并返回退出异常。"""
    console.print(f"[red]Error: {message}[/red]")
    return typer.Exit(1)


def render_provider_build_error(message: str, *, silent: bool = False) -> None:
    """输出 provider 装配错误。"""
    if silent:
        return
    console.print(f"[red]Error: {message}[/red]")
    if "No API key configured" in message:
        console.print("Set one in ~/.nomi/config.json under providers section")
    if "Azure OpenAI requires" in message:
        console.print("Set them in ~/.nomi/config.json under providers.azure_openai section")
        console.print("Use the model field to specify the deployment name.")
