"""channel service 前后台运行 usecase。"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import typer
from loguru import logger

from nomi.channel.service.runtime import SingleChannelRunner
from nomi.channel.service.state import (
    cleanup_stale_service_files,
    ensure_runtime_not_occupied,
    get_service_log_path,
    get_service_pid_path,
    get_service_state,
    get_service_state_path,
    release_service_files_for_pid,
    wait_for_service_registration,
    validate_active_channel_ready,
    wait_for_process_exit,
    write_service_state_file,
)
from nomi.config.paths import get_logs_dir


def build_service_command(
    config: str | None,
    workspace: str | None,
    *,
    instance: str | None = None,
    instance_root: str | None = None,
) -> list[str]:
    """构造后台 service 启动命令。"""
    command = [sys.executable, "-m", "nomi", "channel", "_serve_internal"]
    if config:
        command.extend(["--config", str(Path(config).expanduser().resolve())])
    if instance:
        command.extend(["--instance", instance])
    if instance_root:
        command.extend(["--instance-root", str(Path(instance_root).expanduser().resolve())])
    if workspace:
        command.extend(["--workspace", workspace])
    return command


def follow_log_file(log_path: Path) -> None:
    """实时跟随日志文件。"""
    if not log_path.exists():
        raise typer.BadParameter(f"日志文件不存在：{log_path}")
    with log_path.open("r", encoding="utf-8", errors="replace") as log_file:
        log_file.seek(0, os.SEEK_END)
        try:
            while True:
                line = log_file.readline()
                if line:
                    typer.echo(line, nl=False)
                    continue
                time.sleep(0.2)
        except KeyboardInterrupt:
            raise typer.Exit(0) from None


def start_background_service(
    config_arg: str | None,
    workspace: str | None,
    loaded_config,
    *,
    instance: str | None = None,
    instance_root: str | None = None,
) -> None:
    """后台启动 channel service。"""
    state = get_service_state(loaded_config)
    if state.state == "running":
        owner = state.owner or "unknown"
        typer.echo(f"channel service 已被 {owner} 占用，pid={state.pid}")
        raise typer.Exit(0)
    if state.state == "stale":
        cleanup_stale_service_files(state.pid_path, state.state_path)

    owner = validate_active_channel_ready(loaded_config)
    logs_dir = get_logs_dir()
    log_path = get_service_log_path()
    pid_path = get_service_pid_path()
    state_path = get_service_state_path()
    logs_dir.mkdir(parents=True, exist_ok=True)

    with log_path.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            build_service_command(
                config_arg,
                workspace,
                instance=instance,
                instance_root=instance_root,
            ),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(Path.cwd()),
        )

    registration = wait_for_service_registration(
        pid=process.pid,
        timeout_seconds=3.0,
        state_path=state_path,
    )
    return_code = process.poll()
    if return_code is not None or registration is None:
        cleanup_stale_service_files(pid_path, state_path)
        raise typer.BadParameter(
            f"channel service 启动失败，进程已退出（code={return_code}）。\n请查看日志：{log_path}"
        )

    pid_path.write_text(str(process.pid), encoding="utf-8")
    logger.info(
        "Channel service started in background: owner={} pid={} log={}",
        owner,
        process.pid,
        log_path,
    )
    typer.echo(f"channel service 已启动，owner={owner}，pid={process.pid}")
    typer.echo(f"日志文件：{log_path}")


def stop_background_service(config=None) -> None:
    """停止后台 channel service。"""
    state = get_service_state(config)
    if state.state == "stopped":
        typer.echo("channel service 当前未运行")
        raise typer.Exit(0)
    if state.state == "stale" or state.pid is None:
        cleanup_stale_service_files(state.pid_path, state.state_path)
        typer.echo("channel service 的 pid 文件已失效，已清理")
        raise typer.Exit(0)

    os.kill(state.pid, signal.SIGTERM)
    if not wait_for_process_exit(state.pid, timeout_seconds=5.0):
        raise typer.Exit("channel service 停止超时，请检查进程状态")
    release_service_files_for_pid(
        state.pid,
        pid_path=state.pid_path,
        state_path=state.state_path,
    )
    logger.info("Channel service stopped: pid={}", state.pid)
    typer.echo(f"channel service 已停止，pid={state.pid}")


async def run_active_channel_foreground(loaded_config, runtime_factory) -> None:
    """以前台方式运行当前启用的 channel。"""
    owner = validate_active_channel_ready(loaded_config)
    pid = os.getpid()
    pid_path = get_service_pid_path()
    state_path = get_service_state_path()
    log_path = get_service_log_path()
    runtime = runtime_factory(loaded_config)
    runner = SingleChannelRunner(loaded_config, runtime)
    try:
        await runtime.start()
        await runner.start()
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(pid), encoding="utf-8")
        write_service_state_file(
            owner=owner,
            pid=pid,
            mode="foreground",
            state_path=state_path,
            log_path=log_path,
        )
        await runner.wait()
    finally:
        try:
            await runner.stop()
        finally:
            await runtime.close()
        release_service_files_for_pid(
            pid,
            pid_path=pid_path,
            state_path=state_path,
        )


def restart_background_service(
    config_arg: str | None,
    workspace: str | None,
    loaded_config,
    *,
    instance: str | None = None,
    instance_root: str | None = None,
) -> None:
    """重启后台 channel service；未运行时则直接启动。"""
    state = get_service_state(loaded_config)
    if state.state == "running":
        stop_background_service(loaded_config)
    elif state.state == "stale":
        cleanup_stale_service_files(state.pid_path, state.state_path)
    start_background_service(
        config_arg,
        workspace,
        loaded_config,
        instance=instance,
        instance_root=instance_root,
    )


def run_foreground_channel(loaded_config, runtime_factory) -> None:
    """以前台方式运行当前启用的 channel。"""
    ensure_runtime_not_occupied(loaded_config)
    asyncio.run(run_active_channel_foreground(loaded_config, runtime_factory))
