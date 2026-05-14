"""配置 schema 默认值测试。"""

from nomi.config.schema import Config
from nomi.providers.factory.resolution import resolve_active_model


def test_default_model_is_read_from_active_provider() -> None:
    """默认模型应从 active provider 的 provider 配置读取。"""
    cfg = Config()
    assert not hasattr(cfg.agents.defaults, "model")
    assert cfg.providers.mimo.model == "mimo-v2.5"
    assert resolve_active_model(cfg) == "mimo-v2.5"


def test_default_provider_is_custom() -> None:
    """默认 provider 固定为 mimo。"""
    cfg = Config()
    assert cfg.agents.defaults.provider == "mimo"


def test_mimo_token_plan_defaults_are_empty() -> None:
    """MiMo Token Plan 默认不启用，需显式填写专用 key。"""
    cfg = Config()
    assert cfg.providers.mimo.token_plan_api_key == ""
    assert cfg.providers.mimo.token_plan_api_base is None


def test_default_provider_dump_hides_locked_api_base_fields() -> None:
    """默认配置导出时只有 custom 暴露 apiBase。"""
    cfg = Config()
    data = cfg.model_dump(mode="json", by_alias=True)

    assert "apiBase" in data["providers"]["custom"]
    for provider_name, provider_config in data["providers"].items():
        if provider_name == "custom":
            continue
        assert "apiBase" not in provider_config


def test_mimo_default_dump_shape() -> None:
    """MiMo 默认导出形态固定为常规 key、Token Plan key、模型和 headers。"""
    cfg = Config()
    data = cfg.model_dump(mode="json", by_alias=True)

    assert data["providers"]["mimo"] == {
        "apiKey": "",
        "tokenPlanApiKey": "",
        "model": "mimo-v2.5",
        "extraHeaders": None,
    }


def test_reads_nomi_env_prefix(monkeypatch) -> None:
    """支持 NOMI_ 前缀读取配置。"""
    monkeypatch.setenv("NOMI_PROVIDERS__MIMO__MODEL", "env/model")
    cfg = Config()
    assert cfg.providers.mimo.model == "env/model"


def test_ignores_legacy_nanobot_env_prefix(monkeypatch) -> None:
    """不再兼容 NANOBOT_ 前缀。"""
    monkeypatch.delenv("NOMI_PROVIDERS__MIMO__MODEL", raising=False)
    monkeypatch.setenv("NANOBOT_PROVIDERS__MIMO__MODEL", "legacy/model")
    cfg = Config()
    assert cfg.providers.mimo.model == "mimo-v2.5"


def test_channel_defaults() -> None:
    """单入口 channel 默认配置应固定。"""
    cfg = Config()
    assert cfg.channel.kind == ""
    assert cfg.channel.weixin.allow_from == ["*"]
    assert cfg.channel.weixin.base_url == "https://ilinkai.weixin.qq.com"
    assert cfg.channel.weixin.token == ""
    assert cfg.channel.weixin.state_dir == ""
    assert cfg.channel.weixin.poll_timeout == 35
    assert cfg.channel.feishu.app_id == ""


def test_transcription_defaults() -> None:
    """语音转写默认配置应固定为单一 qwen3-asr-flash 入口。"""
    cfg = Config()
    assert cfg.transcription.api_key == ""
    assert cfg.transcription.api_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_instance_key_accepts_chinese_and_rejects_path_separators() -> None:
    """instance.key 允许中文，但不允许作为 session/path 分隔符的字符。"""
    cfg = Config.model_validate({"instance": {"key": "小美"}})
    assert cfg.instance.key == "小美"

    import pytest

    with pytest.raises(ValueError):
        Config.model_validate({"instance": {"key": "bad/key"}})
    with pytest.raises(ValueError):
        Config.model_validate({"instance": {"key": "bad:key"}})
