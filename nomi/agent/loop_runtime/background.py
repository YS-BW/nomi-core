"""AgentLoop 后台系统 owner。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from nomi.bus.events import OutboundMessage

if TYPE_CHECKING:
    from nomi.agent.loop import AgentLoop
    from nomi.cron import CronJob


class BackgroundRuntime:
    """负责 cron、dream、MCP 生命周期相关逻辑。"""

    def __init__(self, loop: "AgentLoop") -> None:
        """绑定后台运行时所属的 AgentLoop。

        参数:
            loop: 当前主循环 owner。

        返回:
            无返回值。
        """
        self._loop = loop

    async def connect_mcp(self) -> None:
        """按需连接 MCP。"""
        await self._loop._mcp.connect()

    async def close(self) -> None:
        """关闭后台任务、cron 和 MCP。"""
        await self._loop._control.close_background()
        await self._loop.cron_service.stop()
        await self._loop._mcp.close()

    def trigger_dream_background(self, channel: str, chat_id: str) -> None:
        """在后台触发一次 dream。"""

        async def _run_dream() -> None:
            started_at = time.monotonic()
            try:
                did_work = await self._loop.dream.run()
                elapsed = time.monotonic() - started_at
                if did_work:
                    content = f"Dream 已完成，耗时 {elapsed:.1f}s。"
                else:
                    content = "Dream：没有需要处理的内容。"
            except Exception as exc:
                elapsed = time.monotonic() - started_at
                content = f"Dream 执行失败，耗时 {elapsed:.1f}s：{exc}"
            await self._loop.bus.publish_outbound(
                OutboundMessage(
                    channel=channel,
                    chat_id=chat_id,
                    content=content,
                )
            )

        self._loop._schedule_background(_run_dream())

    async def run_trigger(self, job: "CronJob") -> None:
        """处理一条已到点的后台时间触发记录。"""
        await self._loop.tasks.run_trigger(job)
