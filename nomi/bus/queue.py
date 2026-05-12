"""异步消息总线队列。"""

import asyncio
from collections.abc import Awaitable, Callable

from nomi.bus.events import InboundMessage, OutboundMessage


class MessageBus:
    """解耦渠道与 Agent 的异步消息总线。"""

    def __init__(self):
        """初始化消息总线。"""
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        self._outbound_subscribers: dict[int, Callable[[OutboundMessage], Awaitable[None] | None]] = {}
        self._next_subscriber_id = 0

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """发布一条入站消息。"""
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """消费下一条入站消息。"""
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """发布一条出站消息。"""
        if not self._outbound_subscribers:
            await self.outbound.put(msg)
            return
        for callback in list(self._outbound_subscribers.values()):
            try:
                result = callback(msg)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                continue

    async def consume_outbound(self) -> OutboundMessage:
        """消费下一条出站消息。"""
        return await self.outbound.get()

    def subscribe_outbound(
        self,
        callback: Callable[[OutboundMessage], Awaitable[None] | None],
    ) -> Callable[[], None]:
        """注册一个出站消息旁路订阅器。

        参数:
            callback: 每次发布出站消息时调用的回调。

        返回:
            一个用于取消订阅的函数。
        """
        subscriber_id = self._next_subscriber_id
        self._next_subscriber_id += 1
        self._outbound_subscribers[subscriber_id] = callback

        def _unsubscribe() -> None:
            self._outbound_subscribers.pop(subscriber_id, None)

        return _unsubscribe

    @property
    def inbound_size(self) -> int:
        """返回待处理入站消息数。"""
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """返回待发送出站消息数。"""
        return self.outbound.qsize()
