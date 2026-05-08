"""共享 remote 协议层测试。"""

from __future__ import annotations

import pytest

from nomi_protocol.remote import (
    PROTOCOL_VERSION,
    REMOTE_COMMAND_TYPES,
    REMOTE_EVENT_TYPES,
    RemoteCommand,
    load_remote_protocol_spec,
)

def test_remote_protocol_spec_matches_python_contract() -> None:
    """共享协议 spec 应与 Python 薄封装保持一致。"""

    spec = load_remote_protocol_spec()

    assert PROTOCOL_VERSION == spec["version"]
    assert list(REMOTE_COMMAND_TYPES) == spec["remoteCommandTypes"]
    assert list(REMOTE_EVENT_TYPES) == spec["remoteEventTypes"]


def test_remote_command_accepts_all_known_command_types() -> None:
    """所有共享命令类型都应能通过 Python 命令模型校验。"""

    for command_type in REMOTE_COMMAND_TYPES:
        command = RemoteCommand(type=command_type)
        assert command.type == command_type


def test_remote_command_rejects_unknown_command_type() -> None:
    """未知命令类型不应通过 Python 命令模型校验。"""

    with pytest.raises(Exception):
        RemoteCommand(type="unknown-command")
