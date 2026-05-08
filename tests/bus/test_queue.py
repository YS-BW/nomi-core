"""消息总线测试。"""

from __future__ import annotations

import asyncio

import pytest

from nomi.bus.events import OutboundMessage
from nomi.bus.queue import MessageBus


@pytest.mark.asyncio
async def test_bus_outbound_subscriber_receives_messages_without_consuming_queue() -> None:
    bus = MessageBus()
    seen: list[str] = []

    unsubscribe = bus.subscribe_outbound(lambda msg: seen.append(msg.content))

    await bus.publish_outbound(
        OutboundMessage(channel="weixin", chat_id="user-1", content="hello")
    )

    consumed = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
    unsubscribe()

    assert seen == ["hello"]
    assert consumed.content == "hello"
