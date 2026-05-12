"""消息总线测试。"""

from __future__ import annotations

import asyncio

import pytest

from nomi.bus.events import OutboundMessage
from nomi.bus.queue import MessageBus


@pytest.mark.asyncio
async def test_bus_outbound_subscriber_receives_messages_without_queue_accumulation() -> None:
    """存在 adapter 订阅者时，outbound 不再进入旧单消费者队列。"""
    bus = MessageBus()
    seen: list[str] = []

    unsubscribe = bus.subscribe_outbound(lambda msg: seen.append(msg.content))

    await bus.publish_outbound(
        OutboundMessage(channel="weixin", chat_id="user-1", content="hello")
    )

    unsubscribe()

    assert seen == ["hello"]
    assert bus.outbound_size == 0


@pytest.mark.asyncio
async def test_bus_outbound_without_subscriber_keeps_cli_queue_path() -> None:
    """没有 adapter 订阅者时，CLI 仍可通过旧 queue 消费出站消息。"""
    bus = MessageBus()

    await bus.publish_outbound(
        OutboundMessage(channel="cli", chat_id="direct", content="hello")
    )

    consumed = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
    assert consumed.content == "hello"
