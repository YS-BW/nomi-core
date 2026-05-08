"""provider 能力层导出。"""

from .transcription import QwenAsrTranscriptionProvider, build_transcription_provider

__all__ = ["QwenAsrTranscriptionProvider", "build_transcription_provider"]
