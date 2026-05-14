"""配置 schema 默认值测试。"""

from nomi.config.schema import Config


def test_default_model_is_mimo_v2_5() -> None:
    """默认模型固定为 mimo-v2.5。"""
    cfg = Config()
    assert cfg.agents.defaults.model == "mimo-v2.5"


def test_default_provider_is_custom() -> None:
    """默认 provider 固定为 mimo。"""
    cfg = Config()
    assert cfg.agents.defaults.provider == "mimo"


def test_mimo_token_plan_defaults_are_empty() -> None:
    """MiMo Token Plan 默认不启用，需显式填写专用 key。"""
    cfg = Config()
    assert cfg.providers.mimo.token_plan_api_key == ""
    assert cfg.providers.mimo.token_plan_api_base is None


def test_reads_nomi_env_prefix(monkeypatch) -> None:
    """支持 NOMI_ 前缀读取配置。"""
    monkeypatch.setenv("NOMI_AGENTS__DEFAULTS__MODEL", "env/model")
    cfg = Config()
    assert cfg.agents.defaults.model == "env/model"


def test_ignores_legacy_nanobot_env_prefix(monkeypatch) -> None:
    """不再兼容 NANOBOT_ 前缀。"""
    monkeypatch.delenv("NOMI_AGENTS__DEFAULTS__MODEL", raising=False)
    monkeypatch.setenv("NANOBOT_AGENTS__DEFAULTS__MODEL", "legacy/model")
    cfg = Config()
    assert cfg.agents.defaults.model == "mimo-v2.5"


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
