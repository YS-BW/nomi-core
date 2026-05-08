"""兼容导出共享 remote 协议定义。"""

from nomi_protocol.remote import (
    PROTOCOL_VERSION,
    REMOTE_COMMAND_TYPES,
    REMOTE_EVENT_TYPES,
    RemoteCommand,
    RemoteCommandType,
    RemoteEventType,
    load_remote_protocol_spec,
)

__all__ = [
    "PROTOCOL_VERSION",
    "REMOTE_COMMAND_TYPES",
    "REMOTE_EVENT_TYPES",
    "RemoteCommand",
    "RemoteCommandType",
    "RemoteEventType",
    "load_remote_protocol_spec",
]
