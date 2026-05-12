"""实例级 runtime service 测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import typer

from nomi.config.schema import Config
from nomi.agent.loop import AgentLoop
from nomi.runtime.service.runner import start_background_service
from nomi.runtime.service.state import RuntimeServiceState, write_service_state_file


def test_write_service_state_file_records_adapters(tmp_path: Path, monkeypatch) -> None:
    """runtime 状态文件应记录 remote/channel adapter 状态。"""
    config = Config()
    config.remote.enabled = True
    config.remote.host = "127.0.0.1"
    config.remote.port = 8765
    config.channel.kind = "weixin"
    config.channel.weixin.token = "token"
    state_path = tmp_path / "runtime-service.json"
    log_path = tmp_path / "runtime-service.log"

    monkeypatch.setattr("nomi.runtime.service.state.get_instance_name", lambda: "default")
    monkeypatch.setattr("nomi.runtime.service.state.get_instance_root", lambda: tmp_path)
    monkeypatch.setattr("nomi.runtime.service.state.get_config_path", lambda: tmp_path / "config.json")

    write_service_state_file(
        pid=123,
        mode="foreground",
        config=config,
        remote_running=True,
        channel_running=True,
        channel_status="running",
        state_path=state_path,
        log_path=log_path,
    )

    raw = state_path.read_text(encoding="utf-8")
    assert '"pid": 123' in raw
    assert '"running": true' in raw
    assert '"kind": "weixin"' in raw
    assert str(log_path) in raw


def test_start_background_service_rejects_legacy_remote(monkeypatch, tmp_path: Path) -> None:
    """旧 remote 独立 service 存活时应拒绝启动统一 runtime。"""
    config = Config()
    monkeypatch.setattr(
        "nomi.runtime.service.runner.get_service_state",
        lambda _config: RuntimeServiceState(
            "stopped",
            None,
            tmp_path / "runtime.log",
            tmp_path / "runtime.pid",
            tmp_path / "runtime.json",
        ),
    )
    monkeypatch.setattr(
        "nomi.remote.service.state.get_service_state",
        lambda: SimpleNamespace(state="running", pid=123),
    )
    monkeypatch.setattr(
        "nomi.channel.service.state.get_service_state",
        lambda: SimpleNamespace(state="stopped", pid=None),
    )

    with pytest.raises(typer.BadParameter, match="旧 remote service"):
        start_background_service(None, None, config)


def test_start_background_service_spawns_runtime_internal(monkeypatch, tmp_path: Path) -> None:
    """后台启动应使用 instance _serve_internal 作为唯一服务入口。"""
    config = Config()
    pid_path = tmp_path / "runtime-service.pid"
    log_path = tmp_path / "runtime-service.log"
    state_path = tmp_path / "runtime-service.json"
    captured: dict[str, object] = {}

    class _FakeProcess:
        pid = 24680

        def poll(self) -> None:
            return None

    def _fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return _FakeProcess()

    monkeypatch.setattr(
        "nomi.runtime.service.runner.get_service_state",
        lambda _config: RuntimeServiceState("stopped", None, log_path, pid_path, state_path),
    )
    monkeypatch.setattr("nomi.runtime.service.runner.get_logs_dir", lambda: tmp_path)
    monkeypatch.setattr("nomi.runtime.service.runner.get_service_log_path", lambda: log_path)
    monkeypatch.setattr("nomi.runtime.service.runner.get_service_pid_path", lambda: pid_path)
    monkeypatch.setattr("nomi.runtime.service.runner.get_service_state_path", lambda: state_path)
    monkeypatch.setattr(
        "nomi.remote.service.state.get_service_state",
        lambda: SimpleNamespace(state="stopped", pid=None),
    )
    monkeypatch.setattr(
        "nomi.channel.service.state.get_service_state",
        lambda: SimpleNamespace(state="stopped", pid=None),
    )
    monkeypatch.setattr("nomi.runtime.service.runner.subprocess.Popen", _fake_popen)
    monkeypatch.setattr(
        "nomi.runtime.service.runner.wait_for_service_registration",
        lambda **_kwargs: {"pid": _FakeProcess.pid},
    )

    start_background_service(None, None, config, instance="default")

    command = captured["command"]
    assert command[:4] == [__import__("sys").executable, "-m", "nomi", "instance"]
    assert command[4] == "_serve_internal"
    assert pid_path.read_text(encoding="utf-8") == str(_FakeProcess.pid)


def test_agent_loop_set_reminder_consumers_updates_scheduler_owner() -> None:
    """统一 runtime 挂载 adapter 后，scheduler owner 不应继续显示 cli。"""
    captured: dict[str, str] = {}

    class _Tasks:
        def set_scheduler_owner_name(self, owner: str) -> None:
            captured["owner"] = owner

    loop = SimpleNamespace(tasks=_Tasks())

    AgentLoop.set_reminder_consumers(loop, ["remote", "weixin"])

    assert loop.reminder_consumer == "remote"
    assert loop.reminder_consumers == {"remote", "weixin"}
    assert captured["owner"] == "runtime"


def test_agent_loop_empty_reminder_consumers_still_uses_runtime_owner() -> None:
    """统一 runtime 即使未挂 adapter，也应以 runtime 身份持有 scheduler。"""
    captured: dict[str, str] = {}

    class _Tasks:
        def set_scheduler_owner_name(self, owner: str) -> None:
            captured["owner"] = owner

    loop = SimpleNamespace(tasks=_Tasks())

    AgentLoop.set_reminder_consumers(loop, [])

    assert loop.reminder_consumer is None
    assert loop.reminder_consumers == set()
    assert captured["owner"] == "runtime"
