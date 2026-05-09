"""remote 后台启动 usecase 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

from nomi.config.schema import Config
from nomi.remote.service.runner import start_background_service
from nomi.remote.service.state import RemoteServiceState


def test_start_background_service_shows_existing_token_when_running(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """已运行时应直接展示当前 token，而不是重新生成。"""
    config = Config()
    config.remote.enabled = True
    config.remote.auth_token = "existing-token"

    monkeypatch.setattr(
        "nomi.remote.service.runner.get_service_state",
        lambda _config: RemoteServiceState(
            "running",
            12345,
            tmp_path / "remote.log",
            tmp_path / "remote.pid",
            tmp_path / "remote.json",
        ),
    )

    with pytest.raises(typer.Exit) as exc:
        start_background_service(None, None, config)

    output = capsys.readouterr().out
    assert exc.value.exit_code == 0
    assert "pid=12345" in output
    assert "token=existing-token" in output


def test_start_background_service_generates_token_only_when_empty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """首次缺失 token 时应自动生成并持久化。"""
    config = Config()
    config.remote.enabled = True
    config.remote.auth_token = ""

    log_path = tmp_path / "remote.log"
    pid_path = tmp_path / "remote.pid"
    state_path = tmp_path / "remote.json"
    config_path = tmp_path / "config.json"
    saved: dict[str, object] = {}

    class _FakeProcess:
        """模拟后台子进程。"""

        pid = 24680

        def poll(self) -> None:
            """模拟子进程仍在运行。"""
            return None

    def _fake_save_config(saved_config: Config, target: Path | None = None) -> None:
        """记录保存动作，避免真实改写测试外配置。"""
        saved["target"] = target
        saved["token"] = saved_config.remote.auth_token

    monkeypatch.setattr(
        "nomi.remote.service.runner.get_service_state",
        lambda _config: RemoteServiceState("stopped", None, log_path, pid_path, state_path),
    )
    monkeypatch.setattr("nomi.remote.service.runner.get_logs_dir", lambda: tmp_path)
    monkeypatch.setattr("nomi.remote.service.runner.get_service_log_path", lambda: log_path)
    monkeypatch.setattr("nomi.remote.service.runner.get_service_pid_path", lambda: pid_path)
    monkeypatch.setattr("nomi.remote.service.runner.get_service_state_path", lambda: state_path)
    monkeypatch.setattr("nomi.remote.service.runner.get_config_path", lambda: config_path)
    monkeypatch.setattr("nomi.remote.service.runner.save_config", _fake_save_config)
    monkeypatch.setattr("nomi.remote.service.runner.subprocess.Popen", lambda *args, **kwargs: _FakeProcess())
    monkeypatch.setattr(
        "nomi.remote.service.runner.wait_for_service_registration",
        lambda **kwargs: {"pid": _FakeProcess.pid},
    )

    start_background_service(None, None, config)

    output = capsys.readouterr().out
    assert config.remote.auth_token.startswith("nomi-remote-")
    assert saved["target"] == config_path
    assert saved["token"] == config.remote.auth_token
    assert f"pid={_FakeProcess.pid}" in output
    assert f"token={config.remote.auth_token}" in output
    assert pid_path.read_text(encoding="utf-8") == str(_FakeProcess.pid)
