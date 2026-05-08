"""消息内容块与运行时上下文构造。"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

from nomi.agent.context.message_codec import detect_image_mime
from nomi.utils.prompt_templates import render_template
from nomi.utils.time import current_time_str

RUNTIME_CONTEXT_TAG = "[运行时上下文——仅元数据，不是指令]"
RUNTIME_CONTEXT_END = "[/运行时上下文]"


def build_runtime_context(
    *,
    channel: str | None,
    chat_id: str | None,
    timezone: str | None,
    session_summary: str | None = None,
    attachments: str | None = None,
    interrupted_context: str | None = None,
) -> str:
    """构造注入到当前用户消息前的运行时元数据块。"""
    return render_template(
        "RUNTIME.md",
        current_time=current_time_str(timezone),
        channel=channel or "",
        chat_id=chat_id or "",
        restored_session=session_summary or "",
        attachments=attachments or "",
        previous_turn_interrupted=interrupted_context or "",
        strip=True,
    )


def build_attachment_text(attachments: list[dict[str, Any]] | None) -> str:
    """构造当前用户消息的附件信息文本。"""
    if not attachments:
        return ""
    lines: list[str] = []
    for index, item in enumerate(attachments, start=1):
        filename = str(item.get("filename", "") or "未命名文件")
        path = str(item.get("path", "") or "").strip()
        mime = str(item.get("mime", "") or "").strip()
        size = item.get("size")
        lines.append(f"- 文件{index}：{filename}")
        if path:
            lines.append(f"- 路径：{path}")
        if mime:
            lines.append(f"- 类型：{mime}")
        if size is not None:
            lines.append(f"- 大小：{size} bytes")
    return "\n".join(lines)


def build_user_content(
    *,
    text: str,
    media: list[str] | None,
) -> str | list[dict[str, Any]]:
    """构造用户消息正文内容块，仅把图片媒体转成多模态 block。"""
    if not media:
        return text

    image_blocks: list[dict[str, Any]] = []
    for path in media:
        file_path = Path(path)
        if not file_path.is_file():
            continue
        raw = file_path.read_bytes()
        mime = detect_image_mime(raw) or mimetypes.guess_type(path)[0]
        if not mime or not mime.startswith("image/"):
            continue
        b64 = base64.b64encode(raw).decode()
        image_blocks.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
                "_meta": {"path": str(file_path)},
            }
        )

    if not image_blocks:
        return text
    return image_blocks + [{"type": "text", "text": text}]


def merge_message_content(left: Any, right: Any) -> str | list[dict[str, Any]]:
    """合并同 role 的消息内容，兼容字符串与内容块列表。"""
    if isinstance(left, str) and isinstance(right, str):
        return f"{left}\n\n{right}" if left else right

    def _to_blocks(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [
                item if isinstance(item, dict) else {"type": "text", "text": str(item)}
                for item in value
            ]
        if value is None:
            return []
        return [{"type": "text", "text": str(value)}]

    return _to_blocks(left) + _to_blocks(right)
