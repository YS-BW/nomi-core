"""用户画像确认与查看命令。"""

from __future__ import annotations

from nomi.bus.events import OutboundMessage
from nomi.command.router import CommandContext


async def cmd_user_review(ctx: CommandContext) -> OutboundMessage:
    """查看待确认的用户画像候选。"""
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=ctx.loop.user_profile.render_review_text(session_key=ctx.key),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_user_apply(ctx: CommandContext) -> OutboundMessage:
    """确认并应用一条用户画像候选。"""
    candidate_id = ctx.args.strip()
    if not candidate_id:
        content = "用法：`/user-apply <id>`"
    else:
        candidate = ctx.loop.user_profile.apply_candidate(candidate_id)
        content = (
            f"已更新 USER.md：{candidate.field} -> {candidate.value}"
            if candidate is not None
            else f"未找到候选：`{candidate_id}`"
        )
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_user_reject(ctx: CommandContext) -> OutboundMessage:
    """拒绝一条用户画像候选。"""
    candidate_id = ctx.args.strip()
    if not candidate_id:
        content = "用法：`/user-reject <id>`"
    else:
        candidate = ctx.loop.user_profile.reject_candidate(candidate_id)
        content = (
            f"已忽略该画像候选：{candidate.field} -> {candidate.value}"
            if candidate is not None
            else f"未找到候选：`{candidate_id}`"
        )
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_user_show(ctx: CommandContext) -> OutboundMessage:
    """查看当前 USER.md。"""
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=ctx.loop.user_profile.render_user_document(),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )
