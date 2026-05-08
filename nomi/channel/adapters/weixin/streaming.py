"""微信流式发送与 typing 管理。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable

from loguru import logger

if TYPE_CHECKING:
    from .channel import WeixinChannel


WEIXIN_STREAM_PART_MARKER = "<part>"
WEIXIN_TYPING_KEEPALIVE_SECONDS = 5.0
WEIXIN_TYPING_STATUS_START = 1
WEIXIN_TYPING_STATUS_STOP = 2


@dataclass
class StreamState:
    """单轮微信流式发送状态。"""

    chat_id: str
    visible_buffer: str = ""
    saw_stream_delta: bool = False
    typing_active: bool = False
    typing_task: asyncio.Task[None] | None = None
    cancelled: bool = False


class WeixinStreamSender:
    """负责微信正文缓冲、分段和 typing 生命周期。"""

    def __init__(
        self,
        channel: "WeixinChannel",
        *,
        send_text: Callable[[str, str, str], Awaitable[None]],
    ) -> None:
        """绑定微信流式发送所需依赖。

        参数:
            channel: 当前微信 channel owner。
            send_text: 实际发送单段文本的回调。

        返回:
            无返回值。
        """
        self._channel = channel
        self._send_text = send_text
        self._states: dict[str, StreamState] = {}

    async def clear_all(self) -> None:
        """清空全部流式状态。"""
        for state_key, state in list(self._states.items()):
            await self._stop_typing_for_state(state_key, state)
        self._states.clear()

    async def cancel_session(self, session_key: str) -> None:
        """取消指定会话下的全部流式发送状态。"""
        for state_key, state in list(self._states.items()):
            if not state_key.startswith(f"{session_key}:") and state_key != session_key:
                continue
            state.cancelled = True
            await self._stop_typing_for_state(state_key, state)
            self._states.pop(state_key, None)

    async def on_delta(self, chat_id: str, content: str, metadata: dict[str, object]) -> None:
        """处理一段微信流式正文增量。"""
        state_key = self._channel._stream_state_key(chat_id, metadata)
        context_token = self._channel._context_tokens.get(chat_id, "")
        if not context_token:
            logger.warning("No weixin context token for {}; drop stream delta.", chat_id)
            await self._drop_state(state_key)
            return

        if self._channel.is_generation_stale(metadata):
            await self._drop_state(state_key)
            return

        state = self._states.setdefault(state_key, StreamState(chat_id=chat_id))
        if state.cancelled:
            await self._drop_state(state_key)
            return

        try:
            if metadata.get("_stream_end"):
                await self._flush_tail(chat_id, context_token, state_key, state)
                return

            if not metadata.get("_stream_delta"):
                return

            state.saw_stream_delta = True

            if not state.typing_active:
                await self._start_typing(chat_id, context_token, state_key, state)

            state.visible_buffer += str(content or "")
            await self._flush_parts(chat_id, context_token, state, keep_tail=True)
        except Exception:
            await self._drop_state(state_key)
            raise

    async def _flush_tail(
        self,
        chat_id: str,
        context_token: str,
        state_key: str,
        state: StreamState,
    ) -> None:
        await self._flush_parts(chat_id, context_token, state, keep_tail=False)
        if state.visible_buffer.strip():
            await self._send_segment(chat_id, context_token, state.visible_buffer.strip())
            state.visible_buffer = ""
        if state.saw_stream_delta:
            self._channel._completed_streams.add(state_key)
        await self._stop_typing(chat_id, state_key, state)
        self._states.pop(state_key, None)

    async def _flush_parts(
        self,
        chat_id: str,
        context_token: str,
        state: StreamState,
        *,
        keep_tail: bool,
    ) -> None:
        parts = state.visible_buffer.split(WEIXIN_STREAM_PART_MARKER)
        if keep_tail:
            state.visible_buffer = parts.pop() if parts else ""
        else:
            state.visible_buffer = ""
        for part in parts:
            segment = part.strip()
            if segment:
                await self._send_segment(chat_id, context_token, segment)

    async def _send_segment(
        self,
        chat_id: str,
        context_token: str,
        text: str,
    ) -> None:
        if not text:
            return
        await self._send_text(chat_id, context_token, text)
        preview_source = text
        preview = (
            preview_source[:80] + "..."
            if len(preview_source) > 80
            else preview_source
        )
        logger.info("Weixin stream chunk sent to {}: {}", chat_id, preview)

    async def _start_typing(
        self,
        chat_id: str,
        context_token: str,
        state_key: str,
        state: StreamState,
    ) -> None:
        state.typing_active = True
        await self._send_typing(chat_id, context_token, WEIXIN_TYPING_STATUS_START)

        async def _keepalive() -> None:
            while True:
                await asyncio.sleep(WEIXIN_TYPING_KEEPALIVE_SECONDS)
                current = self._states.get(state_key)
                if current is not state or not state.typing_active:
                    return
                await self._send_typing(chat_id, context_token, WEIXIN_TYPING_STATUS_START)

        state.typing_task = asyncio.create_task(_keepalive())

    async def _stop_typing(
        self,
        chat_id: str,
        state_key: str,
        state: StreamState,
    ) -> None:
        if not state.typing_active:
            self._stop_background_tasks(state)
            return
        state.typing_active = False
        self._stop_background_tasks(state)
        context_token = self._channel._context_tokens.get(chat_id, "")
        if context_token:
            await self._send_typing(chat_id, context_token, WEIXIN_TYPING_STATUS_STOP)

    async def _stop_typing_for_state(self, state_key: str, state: StreamState) -> None:
        await self._stop_typing(state.chat_id, state_key, state)

    async def _drop_state(self, state_key: str) -> None:
        state = self._states.pop(state_key, None)
        if state is None:
            return
        await self._stop_typing_for_state(state_key, state)

    def _stop_background_tasks(self, state: StreamState) -> None:
        task = state.typing_task
        if task is not None:
            task.cancel()
            state.typing_task = None

    async def _send_typing(self, chat_id: str, context_token: str, status: int) -> None:
        try:
            await self._channel._send_typing(chat_id, context_token, status=status)
        except Exception as exc:
            logger.warning("Weixin typing status={} failed for {}: {}", status, chat_id, exc)
