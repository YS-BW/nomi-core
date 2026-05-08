"""channel 登录流程使用的最小 runtime stub。"""

from __future__ import annotations

from nomi.bus.queue import MessageBus
from nomi.config.schema import Config
from nomi.runtime.models import InterruptResult, RuntimeStatusSnapshot


class ChannelLoginRuntime:
    """仅供 channel 登录阶段使用的最小 runtime。"""

    def __init__(self, config: Config) -> None:
        """绑定登录流程需要读取的配置对象。

        参数:
            config: 当前完整配置。

        返回:
            无返回值。
        """
        self.bus = MessageBus()
        self.config = config

    def interrupt_session(
        self,
        session_id: str,
        reason: str = "user_interrupt",
    ) -> InterruptResult:
        """登录流程不会使用中断控制面。"""
        return InterruptResult(
            session_id=session_id,
            reason=reason,
            accepted=False,
            cancelled_tasks=0,
            already_interrupting=False,
        )

    def reset_session(self, session_id: str) -> None:
        """登录流程不会使用会话重置。"""
        del session_id

    async def get_status_snapshot(self, session_id: str) -> RuntimeStatusSnapshot:
        """登录流程不会使用状态查询。"""
        del session_id
        raise RuntimeError("status snapshot is not available during channel login")

    async def transcribe_audio(self, file_path: str) -> str:
        """登录流程不会使用音频转写。"""
        del file_path
        return ""
