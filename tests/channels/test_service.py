"""单实例 channel adapter runner 测试。"""

from __future__ import annotations

import asyncio

import pytest

from nomi.bus.events import OutboundMessage
from nomi.bus.queue import MessageBus
from nomi.channel.base import BaseChannel
from nomi.channel.service.runtime import SingleChannelRunner
from nomi.config.schema import Config


class _FakeRuntime:
    def __init__(self) -> None:
        self.bus = MessageBus()


class _FakeChannel(BaseChannel):
    name = "weixin"

    def __init__(self, config, runtime) -> None:
        super().__init__(config, runtime)
        self.started = False
        self.stopped = False
        self.messages: list[OutboundMessage] = []
        self.progresses: list[tuple[str, str, bool]] = []
        self.deltas: list[tuple[str, str, dict]] = []
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        self.started = True
        await self._stop_event.wait()

    async def login(self, force: bool = False) -> bool:
        del force
        return True

    async def stop(self) -> None:
        self.stopped = True
        self._stop_event.set()

    async def send_message(self, message: OutboundMessage) -> None:
        self.messages.append(message)

    async def send_progress(self, chat_id: str, content: str, metadata=None, *, tool_hint: bool = False) -> None:
        self.progresses.append((chat_id, content, tool_hint))

    async def send_delta(self, chat_id: str, content: str, metadata=None) -> None:
        self.deltas.append((chat_id, content, dict(metadata or {})))


@pytest.mark.asyncio
async def test_single_channel_runner_routes_outbound_metadata() -> None:
    config = Config()
    config.channel.kind = "weixin"
    runtime = _FakeRuntime()
    runner = SingleChannelRunner(
        config,
        runtime,
        channel_class=_FakeChannel,
    )

    await runner.start()

    await runtime.bus.publish_outbound(
        OutboundMessage(
            channel="weixin",
            chat_id="room1",
            content='task_create_after("提醒我看书")',
            metadata={"_tool_transition": True},
        )
    )
    await runtime.bus.publish_outbound(
        OutboundMessage(
            channel="weixin",
            chat_id="room1",
            content="running",
            metadata={"_progress": True},
        )
    )
    await runtime.bus.publish_outbound(
        OutboundMessage(
            channel="weixin",
            chat_id="room1",
            content="你",
            metadata={"_stream_delta": True},
        )
    )
    await runtime.bus.publish_outbound(
        OutboundMessage(
            channel="weixin",
            chat_id="room1",
            content="",
            metadata={"_stream_end": True, "_resuming": False},
        )
    )
    await runtime.bus.publish_outbound(
        OutboundMessage(
            channel="weixin",
            chat_id="room1",
            content="你好",
            metadata={},
        )
    )

    await asyncio.sleep(0.05)
    channel = runner.channel
    assert isinstance(channel, _FakeChannel)
    assert channel.started is True
    assert channel.progresses == [
        ("room1", 'task_create_after("提醒我看书")', True),
        ("room1", "running", False),
    ]
    assert channel.deltas[0][0:2] == ("room1", "你")
    assert channel.deltas[1][2]["_stream_end"] is True
    assert channel.messages[0].content == "你好"

    await runner.stop()
    assert channel.stopped is True


@pytest.mark.asyncio
async def test_single_channel_runner_keeps_remote_messages_available() -> None:
    """channel runner 订阅 outbound，不应消费掉 remote 消息。"""
    config = Config()
    config.channel.kind = "weixin"
    runtime = _FakeRuntime()
    runner = SingleChannelRunner(
        config,
        runtime,
        channel_class=_FakeChannel,
    )
    seen: list[OutboundMessage] = []
    runtime.bus.subscribe_outbound(lambda message: seen.append(message))

    await runner.start()
    remote_message = OutboundMessage(
        channel="remote",
        chat_id="desktop",
        content="remote-event",
        metadata={},
    )
    await runtime.bus.publish_outbound(remote_message)
    await asyncio.sleep(0.05)

    channel = runner.channel
    assert isinstance(channel, _FakeChannel)
    assert channel.messages == []
    assert seen == [remote_message]

    await runner.stop()


def test_single_channel_runner_initializes_active_channel() -> None:
    config = Config()
    config.channel.kind = "weixin"
    runtime = _FakeRuntime()

    runner = SingleChannelRunner(
        config,
        runtime,
        channel_class=_FakeChannel,
    )

    assert isinstance(runner.channel, _FakeChannel)
    assert runner.owner == "weixin"
