"""CLI runtime/provider 装配。"""

from __future__ import annotations

import typer

from nomi.config.schema import Config
from nomi.providers.factory.build import build_provider
from nomi.runtime import NomiRuntime

from nomi.cli.cli_error import render_provider_build_error


def make_provider(config: Config, *, silent: bool = False):
    """根据当前配置实例化 provider。"""
    try:
        return build_provider(config)
    except ValueError as exc:
        render_provider_build_error(str(exc), silent=silent)
        raise typer.Exit(1) from exc


def make_runtime(config: Config, *, silent: bool = False, reminder_consumer: str | None = None):
    """根据当前配置装配一份 CLI 复用 runtime。"""
    provider_builder = (
        (lambda cfg: make_provider(cfg, silent=True))
        if silent
        else make_provider
    )
    return NomiRuntime.from_config(
        config,
        provider_builder=provider_builder,
        reminder_consumer=reminder_consumer,
    )
