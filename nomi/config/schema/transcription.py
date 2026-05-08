"""语音转写配置模型。"""

from __future__ import annotations

from .base import Base


class TranscriptionConfig(Base):
    """语音转写配置。"""

    api_key: str = ""
    api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
