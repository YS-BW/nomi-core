"""实例级 runtime service 前后台运行。"""

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

from nomi.channel.registry import channel_has_login_state, get_active_channel_kind
from nomi.channel.service.runtime import SingleChannelRunner
from nomi.config.loader import get_config_path, save_config
from nomi.config.paths import get_logs_dir
from nomi.remote.server import RemoteServer
from nomi.remote.service.state import validate_remote_ready
from nomi.runtime.service.state import (
    cleanup_stale_service_files,
    get_service_log_path,
    get_service_pid_path,
    get_service_state,
    get_service_state_path,
    release_service_files_for_pid,
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
    """构造后台 runtime service 启动命令。"""
    command = [sys.executable, "-m", "nomi", "instance", "_serve_internal"]
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
                import time

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
    """后台启动实例 runtime service。"""
    state = get_service_state(loaded_config)
    if state.state == "running":
        typer.echo(f"instance runtime 已运行，pid={state.pid}")
        raise typer.Exit(0)
    if state.state == "stale":
        cleanup_stale_service_files(state.pid_path, state.state_path)

    _raise_if_legacy_services_running()
    _prepare_runtime_config(loaded_config)
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
            f"instance runtime 启动失败，进程已退出（code={return_code}）。\n请查看日志：{log_path}"
        )

    pid_path.write_text(str(process.pid), encoding="utf-8")
    logger.info("Instance runtime started in background: pid={} log={}", process.pid, log_path)
    typer.echo(f"instance runtime 已启动，pid={process.pid}")
    typer.echo(f"日志文件：{log_path}")


def stop_background_service(config=None) -> None:
    """停止后台实例 runtime service。"""
    state = get_service_state(config)
    if state.state == "stopped":
        typer.echo("instance runtime 当前未运行")
        raise typer.Exit(0)
    if state.state == "stale" or state.pid is None:
        cleanup_stale_service_files(state.pid_path, state.state_path)
        typer.echo("instance runtime 的 pid 文件已失效，已清理")
        raise typer.Exit(0)

    os.kill(state.pid, signal.SIGTERM)
    if not wait_for_process_exit(state.pid, timeout_seconds=5.0):
        raise typer.Exit("instance runtime 停止超时，请检查进程状态")
    release_service_files_for_pid(
        state.pid,
        pid_path=state.pid_path,
        state_path=state.state_path,
    )
    logger.info("Instance runtime stopped: pid={}", state.pid)
    typer.echo(f"instance runtime 已停止，pid={state.pid}")


async def run_instance_foreground(loaded_config, runtime_factory) -> None:
    """以前台方式运行实例 runtime service。"""
    _raise_if_legacy_services_running()
    _prepare_runtime_config(loaded_config)
    pid = os.getpid()
    pid_path = get_service_pid_path()
    state_path = get_service_state_path()
    log_path = get_service_log_path()
    runtime = runtime_factory(loaded_config)
    remote_server: RemoteServer | None = None
    channel_runner: SingleChannelRunner | None = None
    remote_running = False
    channel_running = False
    channel_status = ""
    reminder_consumers: list[str] = []

    try:
        if loaded_config.remote.enabled:
            reminder_consumers.append("remote")
        channel_kind = str(get_active_channel_kind(loaded_config) or "").strip()
        if channel_kind and channel_has_login_state(loaded_config, channel_kind):
            reminder_consumers.append(channel_kind)
        runtime.set_reminder_consumers(reminder_consumers)

        await runtime.start()
        if loaded_config.remote.enabled:
            validate_remote_ready(loaded_config)
            remote_server = RemoteServer(loaded_config, runtime)
            await remote_server.start()
            remote_running = True

        if channel_kind:
            if channel_has_login_state(loaded_config, channel_kind):
                channel_runner = SingleChannelRunner(loaded_config, runtime)
                await channel_runner.start()
                channel_running = True
                channel_status = "running"
            else:
                channel_status = "missing_login"
                logger.warning(
                    "{} channel enabled but login state is missing; channel adapter skipped",
                    channel_kind,
                )

        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(pid), encoding="utf-8")
        write_service_state_file(
            pid=pid,
            mode="foreground",
            config=loaded_config,
            remote_running=remote_running,
            channel_running=channel_running,
            channel_status=channel_status,
            state_path=state_path,
            log_path=log_path,
        )
        await _wait_forever()
    finally:
        if channel_runner is not None:
            await channel_runner.stop()
        if remote_server is not None:
            await remote_server.stop()
        await runtime.close()
        release_service_files_for_pid(
            pid,
            pid_path=pid_path,
            state_path=state_path,
        )


def run_foreground_service(loaded_config, runtime_factory) -> None:
    """以前台方式运行实例 runtime service。"""
    asyncio.run(run_instance_foreground(loaded_config, runtime_factory))


def restart_background_service(
    config_arg: str | None,
    workspace: str | None,
    loaded_config,
    *,
    instance: str | None = None,
    instance_root: str | None = None,
) -> None:
    """重启后台实例 runtime service；未运行时直接启动。"""
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


def _prepare_runtime_config(loaded_config) -> None:
    """补齐统一 runtime 启动前必须存在的配置值。"""
    if not loaded_config.remote.enabled:
        return
    current = str(loaded_config.remote.auth_token or "").strip()
    if current:
        return
    token = f"nomi-remote-{secrets.token_hex(16)}"
    loaded_config.remote.auth_token = token
    save_config(loaded_config, get_config_path())


def _raise_if_legacy_services_running() -> None:
    """发现旧 remote/channel 独立 service 仍在运行时拒绝启动。"""
    from nomi.channel.service.state import get_service_state as get_channel_service_state
    from nomi.remote.service.state import get_service_state as get_remote_service_state

    channel_state = get_channel_service_state()
    if channel_state.state == "running":
        raise typer.BadParameter(
            f"检测到旧 channel service 仍在运行，pid={channel_state.pid}。"
            "请先停止旧进程，再启动 instance runtime。"
        )
    remote_state = get_remote_service_state()
    if remote_state.state == "running":
        raise typer.BadParameter(
            f"检测到旧 remote service 仍在运行，pid={remote_state.pid}。"
            "请先停止旧进程，再启动 instance runtime。"
        )


async def _wait_forever() -> None:
    """保持 service 进程存活直到被取消。"""
    while True:
        await asyncio.sleep(3600)
