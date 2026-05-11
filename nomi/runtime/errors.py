"""runtime 配置与重载相关错误。"""

from __future__ import annotations

from typing import Any


class RuntimeConfigError(RuntimeError):
    """runtime 配置类结构化错误基类。"""

    code = "runtime_config_error"

    def __init__(
        self,
        message: str,
        *,
        fields: list[dict[str, Any]] | None = None,
    ) -> None:
        """初始化配置错误。"""
        super().__init__(message)
        self.fields = fields or []


class ProviderNotFoundError(RuntimeConfigError):
    """目标 provider 不存在。"""

    code = "provider_not_found"


class ProviderSettingsInvalidError(RuntimeConfigError):
    """provider 设置内容非法。"""

    code = "provider_settings_invalid"


class ProviderApiBaseNotEditableError(RuntimeConfigError):
    """当前 provider 的 api_base 不允许远端修改。"""

    code = "provider_api_base_not_editable"


class ModelRequiredError(RuntimeConfigError):
    """切换 active provider 时缺少 model。"""

    code = "model_required"


class ActiveProviderNotConfiguredError(RuntimeConfigError):
    """当前 active provider 尚未具备可实例化条件。"""

    code = "active_provider_not_configured"


class RuntimeReloadBusyError(RuntimeConfigError):
    """当前存在运行中 turn，暂时不允许重载 runtime。"""

    code = "runtime_reload_busy"


class RuntimeReloadFailedError(RuntimeConfigError):
    """重载 runtime 时构建新配置失败。"""

    code = "runtime_reload_failed"
