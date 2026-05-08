"""Nomi 进程内 runtime 入口导出。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomi.runtime.app import NomiRuntime
    from nomi.runtime.state import RuntimeState

__all__ = ["NomiRuntime", "RuntimeState"]


def __getattr__(name: str):
    """按需导出 runtime 顶层对象，避免子模块导入时触发循环依赖。

    参数:
        name: 调用方请求的导出名称。

    返回:
        对应的 runtime 导出对象。
    """
    if name == "NomiRuntime":
        from nomi.runtime.app import NomiRuntime

        return NomiRuntime
    if name == "RuntimeState":
        from nomi.runtime.state import RuntimeState

        return RuntimeState
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
