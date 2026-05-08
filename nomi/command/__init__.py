"""Slash 命令路由导出。"""

from nomi.command.handlers.builtin import register_builtin_commands
from nomi.command.router import CommandContext, CommandRouter

__all__ = ["CommandContext", "CommandRouter", "register_builtin_commands"]
