"""remote service 前后台运行 usecase。"""

from __future__ import annotations

import asyncio
import os
import secrets
import signal
import subprocess
import sys
from pathlib import Path

import typer
from loguru import logger

from nomi.config.loader import get_config_path, save_config
from nomi.config.paths import get_logs_dir
from nomi.remote.server import RemoteServer
from nomi.remote.service.state import (
    cleanup_stale_service_files,
    get_service_log_path,
    get_service_pid_path,
    get_service_state,
    get_service_state_path,
    release_service_files_for_pid,
    validate_remote_ready,
    wait_for_process_exit,
    wait_for_service_registration,
    write_service_state_file,
)


def build_service_command(
    config: str | None,
    workspace: str | None,
    *,
    instance: str | None = None,
    instance_root: str | None = None,
) -> list[str]:
    """构造后台 service 启动命令。"""
    command = [sys.executable, "-m", "nomi", "remote", "_serve_internal"]
    if config:
        command.extend(["--config", str(Path(config).expanduser().resolve())])
    if instance:
        command.extend(["--instance", instance])
    if instance_root:
        command.extend(["--instance-root", str(Path(instance_root).expanduser().resolve())])
    if workspace:
        command.extend(["--workspace", workspace])
    return command


def start_background_service(
    config_arg: str | None,
    workspace: str | None,
    loaded_config,
    *,
    instance: str | None = None,
    instance_root: str | None = None,
) -> None:
    """后台启动 remote service。"""
    state = get_service_state(loaded_config)
    if state.state == "running":
        typer.echo(
            f"remote service 已运行，pid={state.pid}，token={loaded_config.remote.auth_token}"
        )
        raise typer.Exit(0)
    if state.state == "stale":
        cleanup_stale_service_files(state.pid_path, state.state_path)

    if loaded_config.remote.enabled:
        _ensure_remote_auth_token(loaded_config)
    validate_remote_ready(loaded_config)
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
            f"remote service 启动失败，进程已退出（code={return_code}）。\n请查看日志：{log_path}"
        )

    pid_path.write_text(str(process.pid), encoding="utf-8")
    logger.info(
        "Remote service started in background: pid={} log={}",
        process.pid,
        log_path,
    )
    typer.echo(
        f"remote service 已启动，pid={process.pid}，token={loaded_config.remote.auth_token}"
    )
    typer.echo(f"日志文件：{log_path}")


def stop_background_service(config=None) -> None:
    """停止后台 remote service。"""
    state = get_service_state(config)
    if state.state == "stopped":
        typer.echo("remote service 当前未运行")
        raise typer.Exit(0)
    if state.state == "stale" or state.pid is None:
        cleanup_stale_service_files(state.pid_path, state.state_path)
        typer.echo("remote service 的 pid 文件已失效，已清理")
        raise typer.Exit(0)

    os.kill(state.pid, signal.SIGTERM)
    if not wait_for_process_exit(state.pid, timeout_seconds=5.0):
        raise typer.Exit("remote service 停止超时，请检查进程状态")
    release_service_files_for_pid(
        state.pid,
        pid_path=state.pid_path,
        state_path=state.state_path,
    )
    logger.info("Remote service stopped: pid={}", state.pid)
    typer.echo(f"remote service 已停止，pid={state.pid}")


async def run_remote_foreground(loaded_config, runtime_factory) -> None:
    """以前台方式运行 remote service。"""
    if loaded_config.remote.enabled:
        _ensure_remote_auth_token(loaded_config)
    validate_remote_ready(loaded_config)
    pid = os.getpid()
    pid_path = get_service_pid_path()
    state_path = get_service_state_path()
    log_path = get_service_log_path()
    runtime = runtime_factory(loaded_config, reminder_consumer="remote")
    server = RemoteServer(loaded_config, runtime)
    try:
        await runtime.start()
        await server.start()
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(pid), encoding="utf-8")
        write_service_state_file(
            pid=pid,
            mode="foreground",
            state_path=state_path,
            log_path=log_path,
        )
        await server.wait()
    finally:
        try:
            await server.stop()
        finally:
            await runtime.close()
        release_service_files_for_pid(
            pid,
            pid_path=pid_path,
            state_path=state_path,
        )


def run_foreground_service(loaded_config, runtime_factory) -> None:
    """以前台方式运行 remote service。"""
    asyncio.run(run_remote_foreground(loaded_config, runtime_factory))


def restart_background_service(
    config_arg: str | None,
    workspace: str | None,
    loaded_config,
    *,
    instance: str | None = None,
    instance_root: str | None = None,
) -> None:
    """重启后台 remote service；未运行时则直接启动。"""
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


def _ensure_remote_auth_token(loaded_config) -> str:
    """为 remote 自动补齐可用 token，并持久化到配置文件。"""
    current = str(loaded_config.remote.auth_token or "").strip()
    if current:
        return current

    token = f"nomi-remote-{secrets.token_hex(16)}"
    loaded_config.remote.auth_token = token
    save_config(loaded_config, get_config_path())
    return token
