"""channel runtime 运行与 outbound 分发。"""

from __future__ import annotations

import asyncio

from loguru import logger

from nomi.bus.events import OutboundMessage
from nomi.channel.base import BaseChannel, ChannelRuntimeControl
from nomi.channel.registry import (
    build_active_channel,
    get_active_channel_config,
    get_active_channel_spec,
)


class SingleChannelRunner:
    """单实例外部 channel runner。"""

    def __init__(
        self,
        config,
        runtime: ChannelRuntimeControl,
        *,
        channel_class: type[BaseChannel] | None = None,
    ) -> None:
        """装配当前唯一激活的外部 channel runner。

        参数:
            config: 当前完整配置。
            runtime: 提供 bus 与控制面的 runtime 抽象。
            channel_class: 可选的测试替身 channel 类。

        返回:
            无返回值。
        """
        spec = get_active_channel_spec(config)
        self.config = config
        self.runtime = runtime
        self.bus = runtime.bus
        self.channel = (
            channel_class(get_active_channel_config(config), runtime)
            if channel_class is not None
            else build_active_channel(config, runtime)
        )
        self.owner = spec.kind
        self._unsubscribe_bus = None
        self._channel_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """启动当前 channel 与 outbound dispatcher。"""
        if self._channel_task is not None:
            return
        self._unsubscribe_bus = self.bus.subscribe_outbound(self._handle_outbound)
        self._channel_task = asyncio.create_task(self.channel.start())
        await asyncio.sleep(0)

    async def wait(self) -> None:
        """等待 channel 主任务结束。"""
        if self._channel_task is not None:
            await asyncio.gather(self._channel_task, return_exceptions=True)

    async def stop(self) -> None:
        """停止当前 channel 与 dispatcher。"""
        if self._unsubscribe_bus is not None:
            self._unsubscribe_bus()
            self._unsubscribe_bus = None
        try:
            await self.channel.stop()
        finally:
            if self._channel_task is not None:
                await asyncio.gather(self._channel_task, return_exceptions=True)
                self._channel_task = None

    async def _handle_outbound(self, message: OutboundMessage) -> None:
        """旁路订阅 runtime bus 出站消息并路由到当前 channel。"""
        try:
            await self._route_message(message)
        except Exception as exc:
            logger.warning(
                "Channel {} failed to send outbound message to {}: {}",
                self.owner,
                message.chat_id,
                exc,
            )

    async def _route_message(self, message: OutboundMessage) -> None:
        """根据 metadata 选择发送路径。"""
        metadata = dict(message.metadata or {})
        if message.channel != self.owner:
            logger.debug(
                "Drop outbound message for channel {} because active owner is {}",
                message.channel,
                self.owner,
            )
            return
        if metadata.get("_tool_transition"):
            await self.channel.send_progress(
                message.chat_id,
                message.content,
                metadata,
                tool_hint=True,
            )
            return
        if metadata.get("_progress"):
            await self.channel.send_progress(
                message.chat_id,
                message.content,
                metadata,
                tool_hint=False,
            )
            return
        if metadata.get("_stream_delta") or metadata.get("_stream_end"):
            await self.channel.send_delta(message.chat_id, message.content, metadata)
            return
        await self.channel.send_message(message)
