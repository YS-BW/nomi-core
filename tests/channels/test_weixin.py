"""个人微信 channel 测试。"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from nomi.bus.events import OutboundMessage
from nomi.bus.queue import MessageBus
from nomi.channel.adapters.weixin.channel import WeixinChannel
from nomi.config.instance import instance_context_scope
from nomi.config.schema import Config
from nomi.session.errors import SessionNotFoundError


class _FakeRuntime:
    def __init__(self) -> None:
        self.bus = MessageBus()
        self.transcribe_audio = AsyncMock(return_value="")
        self.interrupt_session = MagicMock()
        self.drop_pending_session_messages = MagicMock(return_value=0)

def _make_channel(tmp_path: Path, *, allow_from: list[str] | None = None) -> WeixinChannel:
    config = Config().channel.weixin
    config.state_dir = str(tmp_path)
    if allow_from is not None:
        config.allow_from = allow_from
    runtime = _FakeRuntime()
    runtime.config = Config()
    runtime.config.agents.defaults.workspace = str(tmp_path / "workspace")
    return WeixinChannel(config, runtime)


def test_weixin_print_qr_code_always_prints_login_url(capsys) -> None:
    WeixinChannel._print_qr_code("https://example.com/login")

    captured = capsys.readouterr()
    assert "Login URL: https://example.com/login" in captured.out


def test_weixin_print_qr_code_uses_qrcode_when_available(monkeypatch, capsys) -> None:
    class _FakeQRCode:
        def __init__(self, border: int) -> None:
            self.border = border
            self.data: str | None = None
            self.fit: bool | None = None
            self.print_called = False
            self.invert: bool | None = None

        def add_data(self, data: str) -> None:
            self.data = data

        def make(self, fit: bool) -> None:
            self.fit = fit

        def print_ascii(self, invert: bool = False) -> None:
            self.print_called = True
            self.invert = invert
            print("ASCII QR")

    module = type(sys)("qrcode")
    fake_qr = _FakeQRCode(border=1)
    module.QRCode = lambda border=1: fake_qr
    monkeypatch.setitem(sys.modules, "qrcode", module)

    WeixinChannel._print_qr_code("https://example.com/login")

    captured = capsys.readouterr()
    assert "Login URL: https://example.com/login" in captured.out
    assert "ASCII QR" in captured.out
    assert fake_qr.border == 1
    assert fake_qr.data == "https://example.com/login"
    assert fake_qr.fit is True
    assert fake_qr.print_called is True
    assert fake_qr.invert is True


def test_weixin_login_clears_workspace_sessions(tmp_path: Path, monkeypatch) -> None:
    channel = _make_channel(tmp_path)
    sessions_dir = tmp_path / "instance-root" / "sessions"
    with instance_context_scope(instance_root=tmp_path / "instance-root"):
        sessions_dir.mkdir(parents=True, exist_ok=True)
        (sessions_dir / "wx-user.jsonl").write_text("{}", encoding="utf-8")

        async def fake_qr_login() -> bool:
            return True

        monkeypatch.setattr(channel, "_qr_login", fake_qr_login)

        asyncio.run(channel.login())

        assert not sessions_dir.exists()


def test_weixin_login_clears_saved_auth_state_before_relogin(tmp_path: Path, monkeypatch) -> None:
    channel = _make_channel(tmp_path)
    state_path = Path(channel.config.state_dir) / "account.json"
    state_path.write_text(
        json.dumps({"token": "old-token", "context_tokens": {"wx-user": "ctx"}}),
        encoding="utf-8",
    )

    async def fake_qr_login() -> bool:
        return True

    monkeypatch.setattr(channel, "_qr_login", fake_qr_login)

    asyncio.run(channel.login())

    assert not state_path.exists()
    assert channel._token == ""
    assert channel._context_tokens == {}


@pytest.mark.asyncio
async def test_weixin_process_message_publishes_text_inbound(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m1",
            "from_user_id": "wx-user",
            "context_token": "ctx-1",
            "item_list": [
                {"type": 1, "text_item": {"text": "你好"}},
            ],
        }
    )

    inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1.0)
    assert inbound.channel == "weixin"
    assert inbound.sender_id == "wx-user"
    assert inbound.chat_id == "wx-user"
    assert inbound.content == "你好"
    assert inbound.metadata["message_id"] == "m1"
    assert inbound.metadata["_session_id"] == "weixin:wx-user"
    assert inbound.metadata["_session_generation"] == 1
    channel.runtime.interrupt_session.assert_called_once()
    channel.runtime.drop_pending_session_messages.assert_called_once()


@pytest.mark.asyncio
async def test_weixin_process_message_respects_allow_from(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path, allow_from=["friend-a"])

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m2",
            "from_user_id": "stranger",
            "context_token": "ctx-2",
            "item_list": [
                {"type": 1, "text_item": {"text": "hello"}},
            ],
        }
    )

    assert channel.bus.inbound_size == 0


@pytest.mark.asyncio
async def test_weixin_process_message_skips_missing_session_interrupt(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel.runtime.interrupt_session.side_effect = SessionNotFoundError(
        "session not found",
        session_id="weixin:wx-user",
    )

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m2a",
            "from_user_id": "wx-user",
            "context_token": "ctx-2a",
            "item_list": [
                {"type": 1, "text_item": {"text": "hello"}},
            ],
        }
    )

    inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1.0)
    assert inbound.session_key == "weixin:wx-user"


@pytest.mark.asyncio
async def test_weixin_process_message_deduplicates_message_id(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    message = {
        "message_type": 1,
        "message_id": "m3",
        "from_user_id": "wx-user",
        "context_token": "ctx-3",
        "item_list": [
            {"type": 1, "text_item": {"text": "hello"}},
        ],
    }

    await channel._process_message(message)
    await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1.0)
    await channel._process_message(message)

    assert channel.bus.inbound_size == 0


@pytest.mark.asyncio
async def test_weixin_old_generation_delta_is_dropped(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._token = "token"
    channel._client = object()  # type: ignore[assignment]
    channel._context_tokens["wx-user"] = "ctx"
    channel._session_generations["weixin:wx-user"] = 2
    sent: list[tuple[str, str]] = []

    async def _fake_send(chat_id: str, context_token: str, text: str) -> None:
        sent.append((chat_id, text))

    channel._stream_sender._send_text = _fake_send

    await channel.send_delta(
        "wx-user",
        "旧内容",
        {
            "_stream_delta": True,
            "_session_id": "weixin:wx-user",
            "_session_generation": 1,
            "message_id": "m-old",
        },
    )

    assert sent == []


@pytest.mark.asyncio
async def test_weixin_old_generation_final_message_is_dropped(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._token = "token"
    channel._client = object()  # type: ignore[assignment]
    channel._context_tokens["wx-user"] = "ctx"
    channel._session_generations["weixin:wx-user"] = 3
    channel._send_text_message = AsyncMock()

    await channel.send_message(
        OutboundMessage(
            channel="weixin",
            chat_id="wx-user",
            content="旧最终回复",
            metadata={
                "_session_id": "weixin:wx-user",
                "_session_generation": 2,
                "message_id": "m-old-final",
            },
        )
    )

    channel._send_text_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_weixin_process_message_persists_context_token(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m4",
            "from_user_id": "wx-user",
            "context_token": "ctx-4",
            "item_list": [
                {"type": 1, "text_item": {"text": "persist"}},
            ],
        }
    )

    saved = json.loads((tmp_path / "account.json").read_text(encoding="utf-8"))
    assert saved["context_tokens"] == {"wx-user": "ctx-4"}


@pytest.mark.asyncio
async def test_weixin_process_message_publishes_image_inbound_media(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    image_path = tmp_path / "wechat-photo.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xdbfake-jpeg")
    channel._download_image_item = AsyncMock(return_value=str(image_path))

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m-image",
            "from_user_id": "wx-user",
            "context_token": "ctx-image",
            "item_list": [
                {"type": 2, "image_item": {"media": {"full_url": "https://example.com/a.jpg"}}},
            ],
        }
    )

    inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1.0)
    assert inbound.content == "用户发送了一张图片，请结合附件理解。"
    assert inbound.media == [str(image_path)]
    assert inbound.metadata["message_id"] == "m-image"


@pytest.mark.asyncio
async def test_weixin_process_message_merges_text_and_image(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    image_path = tmp_path / "wechat-photo-2.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xdbfake-jpeg-2")
    channel._download_image_item = AsyncMock(return_value=str(image_path))

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m-text-image",
            "from_user_id": "wx-user",
            "context_token": "ctx-text-image",
            "item_list": [
                {"type": 1, "text_item": {"text": "帮我看看"}},
                {"type": 2, "image_item": {"media": {"full_url": "https://example.com/b.jpg"}}},
            ],
        }
    )

    inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1.0)
    assert inbound.content == "帮我看看\n用户发送了一张图片，请结合附件理解。"
    assert inbound.media == [str(image_path)]


@pytest.mark.asyncio
async def test_weixin_process_message_publishes_file_attachment_metadata(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    file_path = tmp_path / "wechat-report.pdf"
    file_path.write_bytes(b"%PDF-1.7 fake")
    channel._download_file_item = AsyncMock(return_value={
        "kind": "file",
        "path": str(file_path),
        "filename": "report.pdf",
        "mime": "application/pdf",
        "size": len(file_path.read_bytes()),
    })

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m-file",
            "from_user_id": "wx-user",
            "context_token": "ctx-file",
            "item_list": [
                {"type": 4, "file_item": {"file_name": "report.pdf"}},
            ],
        }
    )

    inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1.0)
    assert inbound.content == "用户发送了文件，请结合附件处理。"
    assert inbound.media == [str(file_path)]
    assert inbound.metadata["attachments"] == [{
        "kind": "file",
        "path": str(file_path),
        "filename": "report.pdf",
        "mime": "application/pdf",
        "size": len(file_path.read_bytes()),
    }]


@pytest.mark.asyncio
async def test_weixin_process_message_file_download_failure_keeps_clear_text(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._download_file_item = AsyncMock(return_value=None)

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m-file-fail",
            "from_user_id": "wx-user",
            "context_token": "ctx-file-fail",
            "item_list": [
                {"type": 4, "file_item": {"file_name": "report.pdf"}},
            ],
        }
    )

    inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1.0)
    assert inbound.content == "用户发送了一个文件（report.pdf），但当前未能下载文件内容。"
    assert inbound.media == []
    assert inbound.metadata["attachments"] == []


@pytest.mark.asyncio
async def test_weixin_download_image_item_saves_local_file(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    image_bytes = b"\xff\xd8\xff\xdbplain-jpeg"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://example.com/plain.jpg")
        return httpx.Response(200, content=image_bytes)

    channel._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        saved_path = await channel._download_image_item(
            {"media": {"full_url": "https://example.com/plain.jpg"}}
        )
    finally:
        await channel._client.aclose()
        channel._client = None

    assert saved_path is not None
    saved_file = Path(saved_path)
    assert saved_file.exists()
    assert saved_file.read_bytes() == image_bytes
    assert saved_file.parent.name == "weixin"


@pytest.mark.asyncio
async def test_weixin_download_file_item_saves_local_file_and_metadata(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    file_bytes = b"hello from weixin file"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://example.com/report.txt")
        return httpx.Response(200, content=file_bytes)

    channel._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await channel._download_file_item(
            {
                "file_name": "report.txt",
                "media": {"full_url": "https://example.com/report.txt"},
            }
        )
    finally:
        await channel._client.aclose()
        channel._client = None

    assert result is not None
    saved_file = Path(result["path"])
    assert saved_file.exists()
    assert saved_file.read_bytes() == file_bytes
    assert result["filename"] == "report.txt"
    assert result["mime"] == "text/plain"
    assert result["size"] == len(file_bytes)


@pytest.mark.asyncio
async def test_weixin_process_message_uses_voice_text_when_present(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m-voice-text",
            "from_user_id": "wx-user",
            "context_token": "ctx-voice-text",
            "item_list": [
                {"type": 3, "voice_item": {"text": "帮我查一下天气"}},
            ],
        }
    )

    inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1.0)
    assert inbound.content == "帮我查一下天气"
    assert inbound.media == []
    channel.runtime.transcribe_audio.assert_not_awaited()


@pytest.mark.asyncio
async def test_weixin_process_message_transcribes_voice_via_runtime(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    voice_path = tmp_path / "voice.amr"
    voice_path.write_bytes(b"#!AMR\nvoice")
    channel._download_voice_item = AsyncMock(return_value=str(voice_path))
    channel.runtime.transcribe_audio = AsyncMock(return_value="提醒我明天开会")

    await channel._process_message(
        {
            "message_type": 1,
            "message_id": "m-voice",
            "from_user_id": "wx-user",
            "context_token": "ctx-voice",
            "item_list": [
                {"type": 3, "voice_item": {"media": {"full_url": "https://example.com/voice.amr", "aes_key": "abcd"}}},
            ],
        }
    )

    inbound = await asyncio.wait_for(channel.bus.consume_inbound(), timeout=1.0)
    assert inbound.content == "提醒我明天开会"
    assert inbound.media == [str(voice_path)]
    channel.runtime.transcribe_audio.assert_awaited_once_with(str(voice_path))


@pytest.mark.asyncio
async def test_weixin_send_message_sends_final_text_with_cached_context_token(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-5"
    channel._api_post = AsyncMock(return_value={"errcode": 0})

    await channel.send_message(
        OutboundMessage(channel="weixin", chat_id="wx-user", content="reply")
    )

    channel._api_post.assert_awaited_once()
    assert channel._api_post.await_args.args[1]["msg"]["item_list"][0]["text_item"]["text"] == "reply"


@pytest.mark.asyncio
async def test_weixin_send_message_without_context_token_drops_outbound(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._api_post = AsyncMock(return_value={"errcode": 0})

    await channel.send_message(
        OutboundMessage(channel="weixin", chat_id="wx-user", content="reply")
    )

    channel._api_post.assert_not_awaited()


@pytest.mark.asyncio
async def test_weixin_send_message_uploads_media_files_before_text(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-file-outbound"
    file_path = tmp_path / "report.txt"
    file_path.write_text("hello file", encoding="utf-8")
    channel._send_file_message = AsyncMock()
    channel._send_text_message = AsyncMock()

    await channel.send_message(
        OutboundMessage(
            channel="weixin",
            chat_id="wx-user",
            content="请看附件",
            media=[str(file_path)],
        )
    )

    channel._send_file_message.assert_awaited_once_with(
        "wx-user",
        "ctx-file-outbound",
        str(file_path),
    )
    channel._send_text_message.assert_awaited_once_with(
        "wx-user",
        "ctx-file-outbound",
        "请看附件",
    )


@pytest.mark.asyncio
async def test_weixin_send_message_skips_missing_media_file(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-file-outbound-2"
    missing_path = tmp_path / "missing.pdf"
    channel._send_file_message = AsyncMock()
    channel._send_text_message = AsyncMock()

    await channel.send_message(
        OutboundMessage(
            channel="weixin",
            chat_id="wx-user",
            content="只发文本",
            media=[str(missing_path)],
        )
    )

    channel._send_file_message.assert_not_awaited()
    channel._send_text_message.assert_awaited_once_with(
        "wx-user",
        "ctx-file-outbound-2",
        "只发文本",
    )


@pytest.mark.asyncio
async def test_weixin_send_file_message_uploads_and_sends_file_item(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._sleep_before_send = AsyncMock()
    file_path = tmp_path / "report.txt"
    file_path.write_text("hello file", encoding="utf-8")
    upload_info = {
        "upload_url": "https://cdn.example.com/upload",
        "upload_param": "token=abc",
    }
    channel._get_upload_url = AsyncMock(return_value=upload_info)
    channel._upload_media_bytes = AsyncMock(return_value="encrypted-param")
    channel._api_post = AsyncMock(return_value={"errcode": 0})

    await channel._send_file_message("wx-user", "ctx-raw", str(file_path))

    channel._get_upload_url.assert_awaited_once()
    args = channel._get_upload_url.await_args.args
    assert args[0] == "wx-user"
    assert args[1] == "ctx-raw"
    assert args[2] == 3
    assert channel._upload_media_bytes.await_count == 1
    upload_call = channel._upload_media_bytes.await_args
    assert upload_call.args[0] == "https://cdn.example.com/upload"
    assert upload_call.args[1] == "token=abc"
    assert upload_call.args[2] == file_path.read_bytes()
    sent_body = channel._api_post.await_args.args[1]
    item = sent_body["msg"]["item_list"][0]
    assert item["type"] == 4
    assert item["file_item"]["file_name"] == "report.txt"
    assert item["file_item"]["media"]["encrypt_query_param"] == "encrypted-param"
    assert base64.b64decode(item["file_item"]["aes_key"]).hex() == item["file_item"]["aes_key_hex"]


@pytest.mark.asyncio
async def test_weixin_send_delta_flushes_once_part_marker_appears(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-stream"
    channel._api_post = AsyncMock(return_value={"errcode": 0})
    channel._send_typing = AsyncMock()
    channel._sleep_before_send = AsyncMock()

    await channel.send_delta(
        "wx-user",
        "你好",
        {"_session_id": "weixin:wx-user", "message_id": "m1", "_stream_delta": True},
    )
    channel._api_post.assert_not_awaited()

    await channel.send_delta(
        "wx-user",
        "<part>",
        {"_session_id": "weixin:wx-user", "message_id": "m1", "_stream_delta": True},
    )

    channel._api_post.assert_awaited_once()
    body = channel._api_post.await_args.args[1]
    assert body["msg"]["item_list"][0]["text_item"]["text"] == "你好"
    channel._send_typing.assert_awaited_once_with("wx-user", "ctx-stream", status=1)


@pytest.mark.asyncio
async def test_weixin_send_delta_flushes_multiple_parts_from_single_delta(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-stream-2"
    channel._api_post = AsyncMock(return_value={"errcode": 0})
    channel._send_typing = AsyncMock()
    channel._sleep_before_send = AsyncMock()

    await channel.send_delta(
        "wx-user",
        "第一条消息<part>第二条消息<part>第三条消息<part>",
        {"_session_id": "weixin:wx-user", "message_id": "m2", "_stream_delta": True},
    )

    assert channel._api_post.await_count == 3
    assert channel._api_post.await_args_list[0].args[1]["msg"]["item_list"][0]["text_item"]["text"] == "第一条消息"
    assert channel._api_post.await_args_list[1].args[1]["msg"]["item_list"][0]["text_item"]["text"] == "第二条消息"
    assert channel._api_post.await_args_list[2].args[1]["msg"]["item_list"][0]["text_item"]["text"] == "第三条消息"


@pytest.mark.asyncio
async def test_weixin_send_delta_flushes_when_part_marker_crosses_delta_boundary(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-stream-3"
    channel._api_post = AsyncMock(return_value={"errcode": 0})
    channel._send_typing = AsyncMock()
    channel._sleep_before_send = AsyncMock()

    await channel.send_delta(
        "wx-user",
        "先说前半句",
        {"_session_id": "weixin:wx-user", "message_id": "m3", "_stream_delta": True},
    )
    channel._api_post.assert_not_awaited()

    await channel.send_delta(
        "wx-user",
        "<part>再说后半句",
        {"_session_id": "weixin:wx-user", "message_id": "m3", "_stream_delta": True},
    )

    channel._api_post.assert_awaited_once()
    body = channel._api_post.await_args.args[1]
    assert body["msg"]["item_list"][0]["text_item"]["text"] == "先说前半句"


@pytest.mark.asyncio
async def test_weixin_send_delta_keeps_long_text_buffered_until_part_or_end(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-stream-4"
    channel._api_post = AsyncMock(return_value={"errcode": 0})
    channel._send_typing = AsyncMock()
    channel._sleep_before_send = AsyncMock()
    long_text = (
        "这是一段没有换行但是会越来越长，"
        "而且还会继续往后写很多很多字，"
        "直到超过微信流式单段允许等待的上限，"
        "这时候也不应该直接发出去，"
        "而是要继续等模型自己给出 part，"
        "否则还是会硬切。"
    )

    await channel.send_delta(
        "wx-user",
        long_text,
        {"_session_id": "weixin:wx-user", "message_id": "m4", "_stream_delta": True},
    )

    channel._api_post.assert_not_awaited()


@pytest.mark.asyncio
async def test_weixin_send_delta_flushes_tail_on_stream_end(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-stream-5"
    channel._api_post = AsyncMock(return_value={"errcode": 0})
    channel._send_typing = AsyncMock()
    channel._sleep_before_send = AsyncMock()

    await channel.send_delta(
        "wx-user",
        "还差一点",
        {"_session_id": "weixin:wx-user", "message_id": "m5", "_stream_delta": True},
    )
    channel._api_post.assert_not_awaited()

    await channel.send_delta(
        "wx-user",
        "",
        {"_session_id": "weixin:wx-user", "message_id": "m5", "_stream_end": True},
    )

    assert channel._api_post.await_count == 1
    body = channel._api_post.await_args.args[1]
    assert body["msg"]["item_list"][0]["text_item"]["text"] == "还差一点"
    assert "weixin:wx-user:m5" in channel._completed_streams
    assert channel._send_typing.await_args_list[-1].kwargs["status"] == 2


@pytest.mark.asyncio
async def test_weixin_send_delta_ignores_empty_tail_on_stream_end(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-stream-6"
    channel._api_post = AsyncMock(return_value={"errcode": 0})
    channel._send_typing = AsyncMock()

    await channel.send_delta(
        "wx-user",
        "这段已经完整触发发送。<part>",
        {"_session_id": "weixin:wx-user", "message_id": "m6", "_stream_delta": True},
    )
    assert channel._api_post.await_count == 1
    await channel.send_delta(
        "wx-user",
        "",
        {"_session_id": "weixin:wx-user", "message_id": "m6", "_stream_end": True},
    )
    assert channel._api_post.await_count == 1


@pytest.mark.asyncio
async def test_weixin_send_delta_skips_empty_parts(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-stream-6b"
    channel._api_post = AsyncMock(return_value={"errcode": 0})
    channel._send_typing = AsyncMock()

    await channel.send_delta(
        "wx-user",
        "第一条<part><part>第二条<part>",
        {"_session_id": "weixin:wx-user", "message_id": "m6b", "_stream_delta": True},
    )

    assert channel._api_post.await_count == 2
    assert channel._api_post.await_args_list[0].args[1]["msg"]["item_list"][0]["text_item"]["text"] == "第一条"
    assert channel._api_post.await_args_list[1].args[1]["msg"]["item_list"][0]["text_item"]["text"] == "第二条"


@pytest.mark.asyncio
async def test_weixin_send_message_without_stream_delta_sends_final_text(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-stream-7"
    channel._api_post = AsyncMock(return_value={"errcode": 0})
    await channel.send_message(
        OutboundMessage(
            channel="weixin",
            chat_id="wx-user",
            content="最终整段文本",
            metadata={"_session_id": "weixin:wx-user", "message_id": "m7"},
        )
    )
    channel._api_post.assert_awaited_once()
    assert (
        channel._api_post.await_args.args[1]["msg"]["item_list"][0]["text_item"]["text"]
        == "最终整段文本"
    )


@pytest.mark.asyncio
async def test_weixin_send_message_allows_task_final_text_verbatim(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-cron"
    channel._api_post = AsyncMock(return_value={"errcode": 0})
    channel._sleep_before_send = AsyncMock()

    await channel.send_message(
        OutboundMessage(
            channel="weixin",
            chat_id="wx-user",
            content="该写作业了！<part>别拖啦，现在开始吧💪<part>",
            metadata={"_task_delivery_id": "task_123"},
        )
    )

    assert channel._api_post.await_count == 2
    assert (
        channel._api_post.await_args_list[0].args[1]["msg"]["item_list"][0]["text_item"]["text"]
        == "该写作业了！"
    )
    assert (
        channel._api_post.await_args_list[1].args[1]["msg"]["item_list"][0]["text_item"]["text"]
        == "别拖啦，现在开始吧💪"
    )


@pytest.mark.asyncio
async def test_weixin_send_message_task_skips_empty_parts(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-cron-2"
    channel._api_post = AsyncMock(return_value={"errcode": 0})
    channel._sleep_before_send = AsyncMock()

    await channel.send_message(
        OutboundMessage(
            channel="weixin",
            chat_id="wx-user",
            content="第一条<part><part>第二条<part>",
            metadata={"_task_delivery_id": "task_456"},
        )
    )

    assert channel._api_post.await_count == 2
    assert channel._api_post.await_args_list[0].args[1]["msg"]["item_list"][0]["text_item"]["text"] == "第一条"
    assert channel._api_post.await_args_list[1].args[1]["msg"]["item_list"][0]["text_item"]["text"] == "第二条"


@pytest.mark.asyncio
async def test_weixin_send_message_after_stream_delta_does_not_repeat(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-final-skip"
    channel._api_post = AsyncMock(return_value={"errcode": 0})
    channel._send_typing = AsyncMock()
    channel._sleep_before_send = AsyncMock()

    await channel.send_delta(
        "wx-user",
        "这段已经通过流式发出。",
        {"_session_id": "weixin:wx-user", "message_id": "m8", "_stream_delta": True},
    )
    await channel.send_delta(
        "wx-user",
        "",
        {"_session_id": "weixin:wx-user", "message_id": "m8", "_stream_end": True},
    )
    assert channel._api_post.await_count == 1

    await channel.send_message(
        OutboundMessage(
            channel="weixin",
            chat_id="wx-user",
            content="这段已经通过流式发出。",
            metadata={"_session_id": "weixin:wx-user", "message_id": "m8"},
        )
    )

    assert channel._api_post.await_count == 1


@pytest.mark.asyncio
async def test_weixin_send_delta_sends_typing_keepalive(tmp_path: Path) -> None:
    channel = _make_channel(tmp_path)
    channel._client = object()
    channel._token = "bot-token"
    channel._context_tokens["wx-user"] = "ctx-limit"
    channel._api_post = AsyncMock(return_value={"errcode": 0})
    channel._sleep_before_send = AsyncMock()
    typing_calls: list[int] = []

    async def fake_send_typing(chat_id: str, context_token: str, *, status: int) -> None:
        del chat_id, context_token
        typing_calls.append(status)

    channel._send_typing = fake_send_typing

    await channel.send_delta(
        "wx-user",
        "等待 keepalive 的短句。",
        {"_session_id": "weixin:wx-user", "message_id": "m9", "_stream_delta": True},
    )
    await asyncio.sleep(5.2)
    await channel.send_delta(
        "wx-user",
        "",
        {"_session_id": "weixin:wx-user", "message_id": "m9", "_stream_end": True},
    )

    assert typing_calls[0] == 1
    assert 1 in typing_calls[1:-1]
    assert typing_calls[-1] == 2
    assert typing_calls[-1] == 2
