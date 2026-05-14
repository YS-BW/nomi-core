import json
from pathlib import Path

import pytest

from nomi.config.loader import (
    _resolve_env_vars,
    load_config,
    resolve_config_env_vars,
    save_config,
)


class TestResolveEnvVars:
    def test_replaces_string_value(self, monkeypatch):
        monkeypatch.setenv("MY_SECRET", "hunter2")
        assert _resolve_env_vars("${MY_SECRET}") == "hunter2"

    def test_partial_replacement(self, monkeypatch):
        monkeypatch.setenv("HOST", "example.com")
        assert _resolve_env_vars("https://${HOST}/api") == "https://example.com/api"

    def test_multiple_vars_in_one_string(self, monkeypatch):
        monkeypatch.setenv("USER", "alice")
        monkeypatch.setenv("PASS", "secret")
        assert _resolve_env_vars("${USER}:${PASS}") == "alice:secret"

    def test_nested_dicts(self, monkeypatch):
        monkeypatch.setenv("TOKEN", "abc123")
        data = {"providers": {"openai": {"apiKey": "${TOKEN}"}}}
        result = _resolve_env_vars(data)
        assert result["providers"]["openai"]["apiKey"] == "abc123"

    def test_lists(self, monkeypatch):
        monkeypatch.setenv("VAL", "x")
        assert _resolve_env_vars(["${VAL}", "plain"]) == ["x", "plain"]

    def test_ignores_non_strings(self):
        assert _resolve_env_vars(42) == 42
        assert _resolve_env_vars(True) is True
        assert _resolve_env_vars(None) is None
        assert _resolve_env_vars(3.14) == 3.14

    def test_plain_strings_unchanged(self):
        assert _resolve_env_vars("no vars here") == "no vars here"

    def test_missing_var_raises(self):
        with pytest.raises(ValueError, match="DOES_NOT_EXIST"):
            _resolve_env_vars("${DOES_NOT_EXIST}")


class TestResolveConfig:
    def test_resolves_env_vars_in_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "resolved-key")
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "transcription": {"apiKey": "${TEST_API_KEY}"},
                }
            ),
            encoding="utf-8",
        )

        raw = load_config(config_path)
        assert raw.transcription.api_key == "${TEST_API_KEY}"

        resolved = resolve_config_env_vars(raw)
        assert resolved.transcription.api_key == "resolved-key"

    def test_save_preserves_templates(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MY_TOKEN", "real-token")
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {"providers": {"openai": {"apiKey": "${MY_TOKEN}"}}}
            ),
            encoding="utf-8",
        )

        raw = load_config(config_path)
        save_config(raw, config_path)

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert saved["providers"]["openai"]["apiKey"] == "${MY_TOKEN}"

    def test_load_config_rejects_removed_top_level_keys(self, tmp_path: Path) -> None:
        """已移除顶层配置段仍存在时应直接失败。"""
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "providers": {"custom": {"apiKey": "test-key"}},
                    "api": {"host": "127.0.0.1"},
                    "gateway": {"host": "0.0.0.0"},
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="已移除的顶层字段: api, gateway"):
            load_config(config_path)

    def test_load_config_accepts_channel_schema(self, tmp_path: Path) -> None:
        """新的 channel.kind + channel.weixin 配置应通过校验。"""
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "channel": {
                        "kind": "weixin",
                        "weixin": {
                            "allowFrom": ["friend-a", "friend-b"],
                            "token": "bot-token",
                            "pollTimeout": 45,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        loaded = load_config(config_path)

        assert loaded.channel.kind == "weixin"
        assert loaded.channel.weixin.allow_from == ["friend-a", "friend-b"]
        assert loaded.channel.weixin.token == "bot-token"
        assert loaded.channel.weixin.poll_timeout == 45

    def test_load_config_migrates_legacy_defaults_model_to_provider(self, tmp_path: Path) -> None:
        """旧版 agents.defaults.model 应迁移到 active provider 的 model。"""
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "agents": {"defaults": {"provider": "deepseek", "model": "deepseek-chat"}},
                    "providers": {"deepseek": {"apiKey": "sk-test"}},
                }
            ),
            encoding="utf-8",
        )

        loaded = load_config(config_path)

        assert not hasattr(loaded.agents.defaults, "model")
        assert loaded.agents.defaults.provider == "deepseek"
        assert loaded.providers.deepseek.model == "deepseek-chat"

    def test_load_config_rejects_legacy_channels_shape(self, tmp_path: Path) -> None:
        """旧 channels 根结构不再兼容。"""
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "channels": {"weixin": {"enabled": True}}
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="已移除的 `channels` 根结构"):
            load_config(config_path)

    def test_load_config_rejects_invalid_json(self, tmp_path: Path) -> None:
        """非法 JSON 不应再静默回退到默认配置。"""
        config_path = tmp_path / "config.json"
        config_path.write_text("{invalid json", encoding="utf-8")

        with pytest.raises(ValueError, match="不是合法 JSON"):
            load_config(config_path)

    def test_load_config_accepts_utf8_bom(self, tmp_path: Path) -> None:
        """Windows 工具写入 UTF-8 BOM 时仍应正常加载配置。"""
        config_path = tmp_path / "config.json"
        config_path.write_text(
            "\ufeff" + json.dumps({"agents": {"defaults": {"provider": "custom"}}}),
            encoding="utf-8",
        )

        loaded = load_config(config_path)

        assert loaded.agents.defaults.provider == "custom"
