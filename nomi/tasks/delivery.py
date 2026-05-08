"""自动任务结果投递层。"""

from __future__ import annotations

from nomi.bus.events import OutboundMessage


class TaskDelivery:
    """负责把任务最终结果投递到外部 channel。"""

    def __init__(self, bus) -> None:
        """绑定消息总线。"""
        self._bus = bus

    async def deliver(self, *, task_id: str, channel: str, chat_id: str, content: str) -> None:
        """投递一条最终任务结果。"""
        if not str(content or "").strip():
            return
        await self._bus.publish_outbound(
            OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=content,
                metadata={
                    "_task_delivery_id": task_id,
                },
            )
        )
