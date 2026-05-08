"""onboard 向导共享类型。"""

from __future__ import annotations

from dataclasses import dataclass

from nomi.config.schema import Config


@dataclass
class OnboardResult:
    """保存一次向导会话的结果。"""

    config: Config
    should_save: bool
