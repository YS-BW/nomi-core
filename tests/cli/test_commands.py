"""CLI 主命令测试。"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from nomi.bus.events import OutboundMessage
from nomi.cli.app import app
from nomi.cli.onboard import _try_auto_fill_context_window
from nomi.cli.support.runtime_factory import make_provider
from nomi.config.schema import Config
from nomi.providers.factory.registry import find_by_name
from nomi.runtime.service.state import RuntimeStatusSnapshot

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    """移除终端 ANSI 控制符，方便断言纯文本输出。"""
    ansi_escape = re.compile(r"\x1b\[[0-9;]*m")
    return ansi_escape.sub("", text)


@pytest.fixture
def mock_paths():
    """隔离 onboard 使用的配置和工作区路径。"""
    with (
        patch("nomi.config.loader.get_config_path") as mock_cp,
        patch("nomi.config.loader.save_config") as mock_sc,
        patch("nomi.config.loader.load_config") as mock_lc,
        patch("nomi.cli.commands.onboard.get_workspace_path") as mock_ws,
    ):
        base_dir = Path("./test_onboard_data")
        if base_dir.exists():
            shutil.rmtree(base_dir)
        base_dir.mkdir()

        config_file = base_dir / "config.json"
        workspace_dir = base_dir / "workspace"

        mock_cp.return_value = config_file
        mock_ws.return_value = workspace_dir
        mock_lc.side_effect = lambda _config_path=None: Config()

        def _save_config(config: Config, config_path: Path | None = None) -> None:
            target = config_path or config_file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(config.model_dump(by_alias=True)),
                encoding="utf-8",
            )

        mock_sc.side_effect = _save_config

        yield config_file, workspace_dir, mock_ws

        if base_dir.exists():
            shutil.rmtree(base_dir)


def test_onboard_fresh_install(mock_paths) -> None:
    """首次初始化会创建配置和工作区模板。"""
    config_file, workspace_dir, mock_ws = mock_paths

    result = runner.invoke(app, ["onboard"])

    assert result.exit_code == 0
    assert "已创建配置文件" in result.stdout
    assert "已创建工作区" in result.stdout
    assert "nomi 已就绪" in result.stdout
    assert "获取地址：https://platform.xiaomimimo.com/console/api-keys" in result.stdout
    assert config_file.exists()
    assert (workspace_dir / "AGENTS.md").exists()
    assert (workspace_dir / "memory" / "MEMORY.md").exists()
    assert mock_ws.call_args.args == (Config().workspace_path,)


def test_onboard_existing_config_refresh(mock_paths) -> None:
    """拒绝覆盖时应保留原值并刷新缺省字段。"""
    config_file, workspace_dir, _ = mock_paths
    config_file.write_text('{"existing": true}', encoding="utf-8")

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    assert "配置文件已存在" in result.stdout
    assert "已刷新配置并保留现有值" in result.stdout
    assert workspace_dir.exists()


def test_onboard_existing_config_overwrite(mock_paths) -> None:
    """确认覆盖时应重置为默认配置。"""
    config_file, workspace_dir, _ = mock_paths
    config_file.write_text('{"existing": true}', encoding="utf-8")

    result = runner.invoke(app, ["onboard"], input="y\n")

    assert result.exit_code == 0
    assert "已将配置重置为默认值" in result.stdout
    assert workspace_dir.exists()


def test_onboard_existing_workspace_safe_create(mock_paths) -> None:
    """工作区已存在时不重复创建，但仍会补齐模板。"""
    config_file, workspace_dir, _ = mock_paths
    workspace_dir.mkdir(parents=True)
    config_file.write_text("{}", encoding="utf-8")

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    assert "已创建工作区" not in result.stdout
    assert (workspace_dir / "AGENTS.md").exists()


def test_onboard_help_shows_workspace_and_config_options() -> None:
    """onboard 帮助信息应暴露当前支持的核心参数。"""
    result = runner.invoke(app, ["onboard", "--help"])

    assert result.exit_code == 0
    stripped_output = _strip_ansi(result.stdout)
    assert "--workspace" in stripped_output
    assert "--config" in stripped_output
    assert "--instance" in stripped_output
    assert "--instance-root" in stripped_output
    assert "--wizard" in stripped_output


def test_root_help_shows_only_current_commands() -> None:
    """根帮助页只展示当前保留的命令面。"""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    stripped_output = _strip_ansi(result.stdout)
    assert "onboard" in stripped_output
    assert "instance" in stripped_output
    assert "agent" in stripped_output
    assert "channel" in stripped_output
    assert "remote" in stripped_output
    assert "status" in stripped_output
    assert "channels" not in stripped_output
    assert "serve" not in stripped_output
    assert "gateway" not in stripped_output
    assert "plugins" not in stripped_output


def test_root_help_localizes_builtin_completion_options() -> None:
    """根帮助页里的补全选项说明应为中文。"""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    stripped_output = _strip_ansi(result.stdout)
    assert "为当前 shell 安装补全脚本" in stripped_output
    assert "显示当前 shell" in stripped_output
    assert "的补全脚本" in stripped_output


def test_onboard_interactive_discard_does_not_save_or_create_workspace(
    mock_paths, monkeypatch
) -> None:
    """向导放弃保存时不应落盘任何文件。"""
    config_file, workspace_dir, _ = mock_paths

    from nomi.cli.onboard import OnboardResult

    monkeypatch.setattr(
        "nomi.cli.onboard.run_onboard",
        lambda initial_config: OnboardResult(config=initial_config, should_save=False),
    )

    result = runner.invoke(app, ["onboard", "--wizard"])

    assert result.exit_code == 0
    assert "未保存任何变更" in result.stdout
    assert not config_file.exists()
    assert not workspace_dir.exists()


def test_onboard_uses_explicit_config_and_workspace_paths(tmp_path, monkeypatch) -> None:
    """显式配置路径和工作区路径应写回最终配置。"""
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    result = runner.invoke(
        app,
        ["onboard", "--config", str(config_path), "--workspace", str(workspace_path)],
    )

    assert result.exit_code == 0
    saved = Config.model_validate(json.loads(config_path.read_text(encoding="utf-8")))
    assert saved.workspace_path == workspace_path
    assert (workspace_path / "AGENTS.md").exists()
    compact_output = _strip_ansi(result.stdout).replace("\n", "")
    resolved_config = str(config_path.resolve())
    assert f"--config {resolved_config}" in compact_output


def test_onboard_wizard_preserves_explicit_config_in_next_steps(tmp_path, monkeypatch) -> None:
    """向导模式结束后应继续提示正确的显式配置路径。"""
    config_path = tmp_path / "instance" / "config.json"
    workspace_path = tmp_path / "workspace"

    from nomi.cli.onboard import OnboardResult

    monkeypatch.setattr(
        "nomi.cli.onboard.run_onboard",
        lambda initial_config: OnboardResult(config=initial_config, should_save=True),
    )

    result = runner.invoke(
        app,
        ["onboard", "--wizard", "--config", str(config_path), "--workspace", str(workspace_path)],
    )

    assert result.exit_code == 0
    compact_output = _strip_ansi(result.stdout).replace("\n", "")
    resolved_config = str(config_path.resolve())
    assert f'nomi agent -m "你好！" --config {resolved_config}' in compact_output


def test_config_dump_excludes_oauth_provider_blocks() -> None:
    """已移除 provider 字段不应出现在默认导出结果里。"""
    config = Config()

    providers = config.model_dump(by_alias=True)["providers"]

    assert "openaiCodex" not in providers
    assert "githubCopilot" not in providers


def test_make_provider_rejects_unknown_forced_provider(capsys) -> None:
    """CLI 构造 provider 时也应把未知 provider 作为用户错误暴露。"""
    config = Config()
    config.agents.defaults.provider = "missing-provider"

    with pytest.raises(typer.Exit):
        make_provider(config)

    captured = capsys.readouterr()
    assert "Unknown provider configured: missing-provider" in captured.out


def test_find_by_name_accepts_camel_case_and_hyphen_aliases() -> None:
    """provider 注册表别名解析应保持可用。"""
    assert find_by_name("volcengineCodingPlan") is not None
    assert find_by_name("volcengineCodingPlan").name == "volcengine_coding_plan"
    assert find_by_name("azure-openai") is not None
    assert find_by_name("azure-openai").name == "azure_openai"


@pytest.fixture
def mock_agent_runtime(tmp_path):
    """隔离 agent 命令依赖，只测试命令装配行为。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "default-workspace")

    with (
        patch("nomi.cli.commands.agent.load_runtime_config", return_value=config) as mock_load_runtime_config,
        patch("nomi.cli.commands.agent.sync_workspace_templates") as mock_sync_templates,
        patch("nomi.cli.commands.agent.make_runtime") as mock_make_runtime,
        patch("nomi.cli.commands.agent.print_agent_response") as mock_print_response,
    ):
        runtime = MagicMock()
        runtime.run_once = AsyncMock(
            return_value=OutboundMessage(channel="cli", chat_id="direct", content="mock-response"),
        )
        runtime.start = AsyncMock(return_value=None)
        runtime.close = AsyncMock(return_value=None)
        runtime.bus = MagicMock()
        runtime.agent_loop = MagicMock()
        mock_make_runtime.return_value = runtime

        yield {
            "config": config,
            "load_runtime_config": mock_load_runtime_config,
            "sync_templates": mock_sync_templates,
            "make_runtime": mock_make_runtime,
            "runtime": runtime,
            "print_response": mock_print_response,
        }


def test_agent_help_shows_workspace_and_config_options() -> None:
    """agent 帮助页应保留当前支持的核心参数。"""
    result = runner.invoke(app, ["agent", "--help"])

    assert result.exit_code == 0
    stripped_output = _strip_ansi(result.stdout)
    assert "--workspace" in stripped_output
    assert "--config" in stripped_output
    assert "--instance" in stripped_output
    assert "--instance-root" in stripped_output


def test_agent_uses_default_config_when_no_workspace_or_config_flags(mock_agent_runtime) -> None:
    """未显式覆盖时应使用默认配置装配 agent。"""
    result = runner.invoke(app, ["agent", "-m", "hello"])

    assert result.exit_code == 0
    assert mock_agent_runtime["load_runtime_config"].call_args.args == (None, None)
    assert mock_agent_runtime["load_runtime_config"].call_args.kwargs == {
        "instance": None,
        "instance_root": None,
    }
    assert mock_agent_runtime["sync_templates"].call_args.args == (
        mock_agent_runtime["config"].workspace_path,
    )
    mock_agent_runtime["make_runtime"].assert_called_once_with(
        mock_agent_runtime["config"],
        reminder_consumer="cli",
    )
    mock_agent_runtime["runtime"].run_once.assert_awaited_once()
    mock_agent_runtime["print_response"].assert_called_once_with(
        "mock-response", render_markdown=True, metadata={},
    )


def test_agent_warns_when_default_config_file_is_missing(monkeypatch, tmp_path: Path) -> None:
    """默认配置文件缺失时应提示先运行 onboard。"""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    missing_config = tmp_path / "missing-config.json"

    monkeypatch.setattr("nomi.cli.support.config.get_config_path", lambda: missing_config)
    monkeypatch.setattr("nomi.cli.support.config.load_config", lambda _path=None: config)
    monkeypatch.setattr("nomi.cli.support.config.resolve_config_env_vars", lambda loaded: loaded)
    monkeypatch.setattr("nomi.cli.commands.agent.sync_workspace_templates", lambda *_args, **_kwargs: None)
    runtime = MagicMock()
    runtime.run_once = AsyncMock(return_value=OutboundMessage(channel="cli", chat_id="direct", content="ok"))
    runtime.close = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "nomi.cli.commands.agent.make_runtime",
        lambda _config, reminder_consumer=None: runtime,
    )
    monkeypatch.setattr("nomi.cli.commands.agent.print_agent_response", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, ["agent", "-m", "hello"])

    assert result.exit_code == 0
    stripped = _strip_ansi(result.stdout)
    assert "未找到配置文件" in stripped
    assert "nomi onboard" in stripped


def test_agent_uses_explicit_config_path(mock_agent_runtime, tmp_path: Path) -> None:
    """显式配置路径应传给 load_config。"""
    config_path = tmp_path / "agent-config.json"
    config_path.write_text("{}", encoding="utf-8")

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_path)])

    assert result.exit_code == 0
    assert mock_agent_runtime["load_runtime_config"].call_args.args == (str(config_path), None)
    assert mock_agent_runtime["load_runtime_config"].call_args.kwargs == {
        "instance": None,
        "instance_root": None,
    }


def test_agent_config_sets_active_path(monkeypatch, tmp_path: Path) -> None:
    """agent 命令应把显式配置路径设置为当前活动路径。"""
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}", encoding="utf-8")

    config = Config()
    seen: dict[str, Path] = {}

    monkeypatch.setattr("nomi.cli.support.config.set_config_path", lambda path: seen.__setitem__("config_path", path))
    monkeypatch.setattr("nomi.cli.support.config.load_config", lambda _path=None: config)
    monkeypatch.setattr("nomi.cli.support.config.resolve_config_env_vars", lambda loaded: loaded)
    monkeypatch.setattr("nomi.cli.commands.agent.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr(
        "nomi.cli.commands.agent.make_runtime",
        lambda _config, reminder_consumer=None: MagicMock(
            run_once=AsyncMock(return_value=OutboundMessage(channel="cli", chat_id="direct", content="ok")),
            close=AsyncMock(return_value=None),
        ),
    )
    monkeypatch.setattr("nomi.cli.commands.agent.print_agent_response", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_file)])

    assert result.exit_code == 0
    assert seen["config_path"] == config_file.resolve()


def test_agent_overrides_workspace_path(mock_agent_runtime) -> None:
    """显式工作区路径应覆盖配置值。"""
    workspace_path = Path("/tmp/agent-workspace")

    result = runner.invoke(app, ["agent", "-m", "hello", "-w", str(workspace_path)])

    assert result.exit_code == 0
    assert mock_agent_runtime["load_runtime_config"].call_args.args == (None, str(workspace_path))
    assert mock_agent_runtime["load_runtime_config"].call_args.kwargs == {
        "instance": None,
        "instance_root": None,
    }
    assert mock_agent_runtime["sync_templates"].call_args.args == (
        mock_agent_runtime["config"].workspace_path,
    )
    mock_agent_runtime["make_runtime"].assert_called_once_with(
        mock_agent_runtime["config"],
        reminder_consumer="cli",
    )


def test_agent_workspace_override_wins_over_config_workspace(
    mock_agent_runtime, tmp_path: Path
) -> None:
    """同时传入配置和工作区时，以命令行工作区为准。"""
    config_path = tmp_path / "agent-config.json"
    config_path.write_text("{}", encoding="utf-8")
    workspace_path = Path("/tmp/agent-workspace")

    result = runner.invoke(
        app,
        ["agent", "-m", "hello", "-c", str(config_path), "-w", str(workspace_path)],
    )

    assert result.exit_code == 0
    assert mock_agent_runtime["load_runtime_config"].call_args.args == (
        str(config_path),
        str(workspace_path),
    )
    assert mock_agent_runtime["load_runtime_config"].call_args.kwargs == {
        "instance": None,
        "instance_root": None,
    }
    assert mock_agent_runtime["sync_templates"].call_args.args == (
        mock_agent_runtime["config"].workspace_path,
    )


def test_agent_supports_instance_flags(mock_agent_runtime) -> None:
    """agent 应把实例参数透传到运行时配置解析。"""
    result = runner.invoke(app, ["agent", "-m", "hello", "--instance", "team-a"])

    assert result.exit_code == 0
    assert mock_agent_runtime["load_runtime_config"].call_args.args == (None, None)
    assert mock_agent_runtime["load_runtime_config"].call_args.kwargs == {
        "instance": "team-a",
        "instance_root": None,
    }


def test_agent_rejects_removed_top_level_config_keys(tmp_path: Path) -> None:
    """旧配置仍带 Frozen 顶层字段时应直接提示清理。"""
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "providers": {"custom": {"apiKey": "still-there"}},
                "api": {"host": "127.0.0.1"},
                "gateway": {"host": "0.0.0.0"},
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_file)])

    assert result.exit_code == 1
    stripped_output = _strip_ansi(result.stdout)
    assert "已移除的顶层字段: api, gateway" in stripped_output
    assert "删除这些字段后重试" in stripped_output
    assert "No API key configured" not in stripped_output

def test_status_reports_basic_runtime_state(monkeypatch, tmp_path: Path) -> None:
    """status 命令应输出配置、工作区和模型状态。"""
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    config = Config()
    config.agents.defaults.workspace = str(workspace)
    config.providers.custom.api_key = "test-key"

    monkeypatch.setattr("nomi.cli.support.status.get_config_path", lambda: config_path)
    monkeypatch.setattr("nomi.cli.support.status.load_config", lambda _path=None: config)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    stripped = _strip_ansi(result.stdout)
    assert "Config" in stripped
    assert "Workspace" in stripped
    assert "Provider" in stripped
    assert "Model" in stripped
    assert "Timezone" in stripped
    assert "Channel Enabled" in stripped
    assert "Channel Owner" in stripped
    assert "Channel Running" in stripped
    assert "Channel Logged In" in stripped
    assert "Channel Uptime" in stripped
    assert "Channel Log" in stripped


def test_status_help_shows_instance_options() -> None:
    """status 帮助页应暴露实例参数。"""
    result = runner.invoke(app, ["status", "--help"])

    assert result.exit_code == 0
    stripped = _strip_ansi(result.stdout)
    assert "--instance" in stripped
    assert "--instance-root" in stripped


def test_channel_login_invokes_weixin_login(monkeypatch) -> None:
    """channel login 应调用当前微信登录链。"""
    called: dict[str, object] = {}

    config = Config()
    config.channel.kind = "weixin"
    monkeypatch.setattr("nomi.cli.commands.channel.load_runtime_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        "nomi.cli.commands.channel.login_active_channel",
        lambda loaded, *, force: called.update({"config": loaded, "force": force}) or True,
    )

    result = runner.invoke(app, ["channel", "login", "--force"])

    assert result.exit_code == 0
    assert called["config"] is config
    assert called["force"] is True


def test_channel_login_without_force_still_invokes_login(monkeypatch) -> None:
    """channel login 默认也应执行清状态后的重新登录链路。"""
    called: dict[str, object] = {}

    config = Config()
    config.channel.kind = "weixin"
    monkeypatch.setattr("nomi.cli.commands.channel.load_runtime_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        "nomi.cli.commands.channel.login_active_channel",
        lambda loaded, *, force: called.update({"config": loaded, "force": force}) or True,
    )

    result = runner.invoke(app, ["channel", "login"])

    assert result.exit_code == 0
    assert called["config"] is config
    assert called["force"] is False


def test_channel_without_subcommand_shows_help() -> None:
    """channel 裸调用时应直接展示帮助。"""
    result = runner.invoke(app, ["channel"])

    assert result.exit_code == 0
    stripped = _strip_ansi(result.stdout)
    assert "Manage external channel adapter configuration" in stripped
    assert "enable" in stripped
    assert "disable" in stripped
    assert "login" in stripped
    assert "status" in stripped
    assert "start" not in stripped
    assert "stop" not in stripped


def test_instance_without_subcommand_shows_help() -> None:
    """instance 裸调用时应直接展示帮助。"""
    result = runner.invoke(app, ["instance"])

    assert result.exit_code == 0
    stripped = _strip_ansi(result.stdout)
    assert "Manage nomi instances" in stripped
    assert "list" in stripped
    assert "create" in stripped
    assert "inspect" in stripped
    assert "remove" in stripped
    assert "services" in stripped
    assert "start" in stripped
    assert "stop" in stripped
    assert "restart" in stripped
    assert "log" in stripped


def test_instance_invite_code_prints_runtime_code(monkeypatch) -> None:
    """instance invite-code 应输出 runtime 生成的邀请码。"""
    config = Config()
    runtime = MagicMock()
    runtime.build_instance_invite_code.return_value = "nomi://instance-invite?token=t"

    monkeypatch.setattr("nomi.cli.commands.instance.load_runtime_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr("nomi.cli.commands.instance.make_runtime", lambda loaded: runtime)

    result = runner.invoke(app, ["instance", "invite-code", "--url", "http://example.test"])

    assert result.exit_code == 0
    assert "nomi://instance-invite?token=t" in _strip_ansi(result.stdout)
    runtime.build_instance_invite_code.assert_called_once_with("http://example.test")


def test_instance_relations_prints_table(monkeypatch) -> None:
    """instance relations 应展示关系表。"""
    config = Config()
    runtime = MagicMock()
    runtime.list_instance_relations.return_value = [
        {
            "key": "xmy",
            "name": "小美",
            "url": "http://127.0.0.1:8766",
            "status": "friend",
            "permission": "chat",
        }
    ]

    monkeypatch.setattr("nomi.cli.commands.instance.load_runtime_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr("nomi.cli.commands.instance.make_runtime", lambda loaded: runtime)

    result = runner.invoke(app, ["instance", "relations"])

    assert result.exit_code == 0
    stripped = _strip_ansi(result.stdout)
    assert "xmy" in stripped
    assert "小美" in stripped
    assert "friend" in stripped


def test_instance_invite_from_code_calls_runtime(monkeypatch) -> None:
    """instance invite --from-code 应解析邀请码并发起申请。"""
    config = Config()
    runtime = MagicMock()
    runtime.invite_instance = AsyncMock(return_value={"ok": True})
    code = (
        "nomi://instance-invite?name=default&url=http%3A%2F%2F127.0.0.1%3A8766&token=t"
    )

    monkeypatch.setattr("nomi.cli.commands.instance.load_runtime_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr("nomi.cli.commands.instance.make_runtime", lambda loaded: runtime)

    result = runner.invoke(app, ["instance", "invite", "xmy", "--from-code", code])

    assert result.exit_code == 0
    runtime.invite_instance.assert_awaited_once_with(
        "xmy",
        url=None,
        token=None,
        invite_code=code,
    )


def test_instance_accept_reject_rename_send_call_runtime(monkeypatch) -> None:
    """instance 关系操作命令应调用 runtime。"""
    config = Config()
    runtime = MagicMock()
    runtime.accept_instance_relation = AsyncMock(return_value={"key": "xmy", "permission": "chat"})
    runtime.reject_instance_relation_async = AsyncMock(return_value=True)
    runtime.rename_instance_relation.return_value = {"key": "xmy", "name": "小美"}
    runtime.send_instance_message = AsyncMock(return_value={"content": "pong"})

    monkeypatch.setattr("nomi.cli.commands.instance.load_runtime_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr("nomi.cli.commands.instance.make_runtime", lambda loaded: runtime)

    accepted = runner.invoke(app, ["instance", "accept", "xmy", "--permission", "chat"])
    rejected = runner.invoke(app, ["instance", "reject", "xmy"])
    renamed = runner.invoke(app, ["instance", "rename", "xmy", "小美"])
    sent = runner.invoke(app, ["instance", "send", "xmy", "ping"])

    assert accepted.exit_code == 0
    assert rejected.exit_code == 0
    assert renamed.exit_code == 0
    assert sent.exit_code == 0
    runtime.accept_instance_relation.assert_awaited_once_with("xmy", "chat")
    runtime.reject_instance_relation_async.assert_awaited_once_with("xmy")
    runtime.rename_instance_relation.assert_called_once_with("xmy", "小美")
    runtime.send_instance_message.assert_awaited_once_with("xmy", "ping")
    assert "pong" in _strip_ansi(sent.stdout)


def test_channel_enable_updates_config(monkeypatch) -> None:
    """channel enable 只更新配置，不启动独立 service。"""
    config = Config()
    saved: dict[str, object] = {}

    monkeypatch.setattr("nomi.cli.commands.channel.load_runtime_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        "nomi.cli.commands.channel.save_config",
        lambda saved_config, path: saved.update({"config": saved_config, "path": path}),
    )
    monkeypatch.setattr("nomi.cli.commands.channel.get_config_path", lambda: Path("/tmp/config.json"))

    result = runner.invoke(app, ["channel", "enable", "weixin"])

    assert result.exit_code == 0
    assert config.channel.kind == "weixin"
    assert saved["config"] is config
    assert "instance restart" in _strip_ansi(result.stdout)


def test_channel_disable_updates_config(monkeypatch) -> None:
    """channel disable 只关闭配置里的 active channel。"""
    config = Config()
    config.channel.kind = "weixin"
    saved: dict[str, object] = {}

    monkeypatch.setattr("nomi.cli.commands.channel.load_runtime_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        "nomi.cli.commands.channel.save_config",
        lambda saved_config, path: saved.update({"config": saved_config, "path": path}),
    )
    monkeypatch.setattr("nomi.cli.commands.channel.get_config_path", lambda: Path("/tmp/config.json"))

    result = runner.invoke(app, ["channel", "disable"])

    assert result.exit_code == 0
    assert config.channel.kind == ""
    assert saved["config"] is config
    assert "instance restart" in _strip_ansi(result.stdout)


def test_channel_login_requires_enabled_channel(monkeypatch) -> None:
    """channel login 在未启用 channel 时提示先启用。"""
    monkeypatch.setattr("nomi.cli.commands.channel.load_runtime_config", lambda *_args, **_kwargs: Config())

    result = runner.invoke(app, ["channel", "login"])

    assert result.exit_code == 2
    stripped = _strip_ansi(result.stdout + result.stderr)
    assert "nomi channel enable weixin" in stripped


def test_instance_start_spawns_runtime_service(monkeypatch, tmp_path: Path) -> None:
    """instance start 应启动统一 runtime service。"""
    config = Config()
    captured: dict[str, object] = {}

    monkeypatch.setattr("nomi.cli.commands.instance.load_runtime_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr("nomi.cli.commands.instance.sync_workspace_templates", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "nomi.cli.commands.instance.start_background_service",
        lambda config_arg, workspace, loaded, **kwargs: captured.update(
            {"config_arg": config_arg, "workspace": workspace, "loaded": loaded, **kwargs}
        ),
    )

    result = runner.invoke(app, ["instance", "start", "team-a", "--workspace", str(tmp_path)])

    assert result.exit_code == 0
    assert captured["loaded"] is config
    assert captured["workspace"] == str(tmp_path)
    assert captured["instance"] == "team-a"


def test_instance_restart_spawns_runtime_service(monkeypatch) -> None:
    """instance restart 应走统一 runtime service 重启入口。"""
    config = Config()
    captured: dict[str, object] = {}

    monkeypatch.setattr("nomi.cli.commands.instance.load_runtime_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr("nomi.cli.commands.instance.sync_workspace_templates", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "nomi.cli.commands.instance.restart_background_service",
        lambda config_arg, workspace, loaded, **kwargs: captured.update(
            {"config_arg": config_arg, "workspace": workspace, "loaded": loaded, **kwargs}
        ),
    )

    result = runner.invoke(app, ["instance", "restart", "--instance", "team-a"])

    assert result.exit_code == 0
    assert captured["loaded"] is config
    assert captured["instance"] == "team-a"


def test_instance_stop_stops_runtime_service(monkeypatch) -> None:
    """instance stop 应停止统一 runtime service。"""
    config = Config()
    called: dict[str, object] = {}

    monkeypatch.setattr("nomi.cli.commands.instance.load_runtime_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        "nomi.cli.commands.instance.stop_background_service",
        lambda loaded: called.update({"loaded": loaded}),
    )

    result = runner.invoke(app, ["instance", "stop", "default"])

    assert result.exit_code == 0
    assert called["loaded"] is config


def test_remote_enable_updates_config_and_generates_token(monkeypatch) -> None:
    """remote enable 只更新配置和 token。"""
    config = Config()
    saved: dict[str, object] = {}

    monkeypatch.setattr("nomi.cli.commands.remote.load_runtime_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        "nomi.cli.commands.remote.save_config",
        lambda saved_config, path: saved.update({"config": saved_config, "path": path}),
    )
    monkeypatch.setattr("nomi.cli.commands.remote.get_config_path", lambda: Path("/tmp/config.json"))
    monkeypatch.setattr("nomi.cli.commands.remote._generate_remote_token", lambda: "token-1")

    result = runner.invoke(app, ["remote", "enable", "--host", "0.0.0.0", "--port", "9999"])

    assert result.exit_code == 0
    assert config.remote.enabled is True
    assert config.remote.host == "0.0.0.0"
    assert config.remote.port == 9999
    assert config.remote.auth_token == "token-1"
    assert saved["config"] is config


def test_remote_token_persists_when_missing(monkeypatch) -> None:
    """remote token 缺失时应生成并保存。"""
    config = Config()
    saved: dict[str, object] = {}

    monkeypatch.setattr("nomi.cli.commands.remote.load_runtime_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        "nomi.cli.commands.remote.save_config",
        lambda saved_config, path: saved.update({"config": saved_config, "path": path}),
    )
    monkeypatch.setattr("nomi.cli.commands.remote.get_config_path", lambda: Path("/tmp/config.json"))
    monkeypatch.setattr("nomi.cli.commands.remote._generate_remote_token", lambda: "token-2")

    result = runner.invoke(app, ["remote", "token"])

    assert result.exit_code == 0
    assert "token-2" in result.stdout
    assert config.remote.auth_token == "token-2"
    assert saved["config"] is config


def test_status_reports_channel_runtime_state(monkeypatch, tmp_path: Path) -> None:
    """status 应输出统一 channel 启用、登录、后台运行状态。"""
    config_path = tmp_path / "config.json"
    workspace = tmp_path / "workspace"
    weixin_dir = tmp_path / "weixin"
    workspace.mkdir()
    weixin_dir.mkdir()
    state_path = weixin_dir / "account.json"
    state_path.write_text("{}", encoding="utf-8")

    config = Config()
    config.agents.defaults.workspace = str(workspace)
    config.agents.defaults.provider = "mimo"
    config.agents.defaults.model = "mimo-v2.5"
    config.agents.defaults.timezone = "Asia/Shanghai"
    config.channel.kind = "weixin"
    config.channel.weixin.state_dir = str(weixin_dir)

    monkeypatch.setattr("nomi.cli.support.status.get_config_path", lambda: config_path)
    monkeypatch.setattr("nomi.cli.support.status.load_config", lambda _path=None: config)
    monkeypatch.setattr(
        "nomi.tasks.runner.TaskRunner.read_scheduler_owner_info",
        lambda _self: {"owner": "weixin", "acquired_at_ms": "123"},
    )
    monkeypatch.setattr(
        "nomi.cli.support.status.build_runtime_status_snapshot",
        lambda *_args, **_kwargs: RuntimeStatusSnapshot(
            running=True,
            uptime_text="1h 2m 3s",
            log_path=tmp_path / "runtime-service.log",
            pid=1357,
            service_state="running",
            remote_enabled=False,
            remote_running=False,
            remote_host="127.0.0.1",
            remote_port=8765,
            channel_enabled=True,
            channel_running=True,
            channel_kind="weixin",
            channel_logged_in=True,
            scheduler_owner="runtime",
        ),
    )
    monkeypatch.setattr(
        "nomi.cli.support.status.Path.home",
        lambda *_args, **_kwargs: tmp_path,
    )

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    stripped = _strip_ansi(result.stdout)
    assert "Provider" in stripped
    assert "mimo" in stripped
    assert "Model" in stripped
    assert "mimo-v2.5" in stripped
    assert "Timezone" in stripped
    assert "Asia/Shanghai" in stripped
    assert "Task Scheduler Owner" in stripped
    assert "Task Scheduler Active" in stripped
    assert "Runtime Running" in stripped
    assert "Runtime PID" in stripped
    assert "Channel Enabled" in stripped
    assert "Channel Owner" in stripped
    assert "Channel Running" in stripped
    assert "weixin" in stripped
    assert "Channel Logged In" in stripped
    assert "Channel Uptime" in stripped
    assert "Runtime Log" in stripped


def test_status_reports_remote_runtime_state(monkeypatch, tmp_path: Path) -> None:
    """status 应输出 remote 的运行与日志信息。"""
    config_path = tmp_path / "config.json"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    config = Config()
    config.agents.defaults.workspace = str(workspace)
    config.remote.enabled = True
    config.remote.host = "127.0.0.1"
    config.remote.port = 8765

    monkeypatch.setattr("nomi.cli.support.status.get_config_path", lambda: config_path)
    monkeypatch.setattr("nomi.cli.support.status.load_config", lambda _path=None: config)
    monkeypatch.setattr(
        "nomi.tasks.runner.TaskRunner.read_scheduler_owner_info",
        lambda _self: {"owner": "remote", "acquired_at_ms": "123"},
    )
    monkeypatch.setattr(
        "nomi.cli.support.status.build_runtime_status_snapshot",
        lambda *_args, **_kwargs: RuntimeStatusSnapshot(
            running=True,
            uptime_text="2h 3m 4s",
            log_path=tmp_path / "runtime-service.log",
            pid=2468,
            service_state="running",
            remote_enabled=True,
            remote_running=True,
            remote_host="127.0.0.1",
            remote_port=8765,
            channel_enabled=False,
            channel_running=False,
            channel_kind=None,
            channel_logged_in=False,
            scheduler_owner="runtime",
        ),
    )
    monkeypatch.setattr("nomi.cli.support.status.Path.home", lambda *_args, **_kwargs: tmp_path)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    stripped = _strip_ansi(result.stdout)
    assert "Remote Enabled" in stripped
    assert "yes" in stripped
    assert "Task Scheduler Owner" in stripped
    assert "remote" in stripped
    assert "Remote Running" in stripped
    assert "Remote Host" in stripped
    assert "127.0.0.1" in stripped
    assert "Remote Port" in stripped
    assert "8765" in stripped
    assert "Runtime Running" in stripped
    assert "Runtime Log" in stripped


def test_onboard_auto_fills_context_window_via_model_catalog(monkeypatch) -> None:
    """向导应通过模型目录推荐上下文窗口。"""
    defaults = Config().agents.defaults
    defaults.model = "mimo-v2.5"
    defaults.provider = "mimo"

    monkeypatch.setattr(
        "nomi.cli.onboard.get_model_context_limit",
        lambda model, provider: 65_536 if (model, provider) == ("mimo-v2.5", "mimo") else None,
    )

    _try_auto_fill_context_window(defaults, "mimo-v2.5")

    assert defaults.context_window_tokens == 65_536


def test_onboard_does_not_auto_fill_context_window_for_unsupported_provider(monkeypatch) -> None:
    """未覆盖的 provider 不应强行写入推荐窗口。"""
    defaults = Config().agents.defaults
    defaults.model = "llama3.2"
    defaults.provider = "ollama"

    monkeypatch.setattr("nomi.cli.onboard.get_model_context_limit", lambda *_args, **_kwargs: None)

    _try_auto_fill_context_window(defaults, "llama3.2")

    assert defaults.context_window_tokens == 65_536
