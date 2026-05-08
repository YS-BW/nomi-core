"""内置 slash 命令协议与注册入口。"""

from __future__ import annotations

from nomi.command.handlers.dream import cmd_dream, cmd_dream_log, cmd_dream_restore
from nomi.command.handlers.runtime import cmd_help, cmd_restart, cmd_status
from nomi.command.handlers.session import cmd_new
from nomi.command.handlers.skills import cmd_skill_manage
from nomi.command.handlers.user_profile import (
    cmd_user_apply,
    cmd_user_reject,
    cmd_user_review,
    cmd_user_show,
)
from nomi.command.router import CommandRouter

SLASH_COMMAND_SPECS: list[tuple[str, str]] = [
    ("/new", "开始新会话"),
    ("/restart", "重启 nomi"),
    ("/status", "查看当前状态"),
    ("/dream", "手动触发 Dream 整理"),
    ("/dream-log", "查看最近一次 Dream 变更"),
    ("/dream-restore", "恢复到之前的 Dream 版本"),
    ("/user-review", "查看待确认的用户画像候选"),
    ("/user-apply <id>", "确认并写入一条用户画像"),
    ("/user-reject <id>", "忽略一条用户画像候选"),
    ("/user-show", "查看当前 USER.md"),
    ("/skill list", "查看当前已安装 skills"),
    ("/skill install <source>", "安装一个 skill"),
    ("/skill uninstall <name>", "卸载一个 skill"),
    ("/help", "查看可用命令"),
]


def build_help_text() -> str:
    """构造各渠道共用的帮助文本。

    参数:
        无。

    返回:
        当前可用 slash 命令的展示文本。
    """
    lines = ["🍌 nomi 命令："]
    lines.extend(f"{command} — {description}" for command, description in SLASH_COMMAND_SPECS)
    return "\n".join(lines)


def register_builtin_commands(router: CommandRouter) -> None:
    """注册默认内置 slash 命令。

    参数:
        router: 当前命令路由器。

    返回:
        无返回值。
    """
    router.priority("/restart", cmd_restart)
    router.priority("/status", cmd_status)
    router.exact("/new", cmd_new)
    router.exact("/status", cmd_status)
    router.exact("/dream", cmd_dream)
    router.exact("/dream-log", cmd_dream_log)
    router.prefix("/dream-log ", cmd_dream_log)
    router.exact("/dream-restore", cmd_dream_restore)
    router.prefix("/dream-restore ", cmd_dream_restore)
    router.exact("/user-review", cmd_user_review)
    router.exact("/user-show", cmd_user_show)
    router.prefix("/user-apply ", cmd_user_apply)
    router.prefix("/user-reject ", cmd_user_reject)
    router.prefix("/skill ", cmd_skill_manage)
    router.exact("/help", cmd_help)
