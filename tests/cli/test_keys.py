import asyncio
import time

import pytest

from nomi.cli.keys import (
    EscInterruptWatcher,
    WindowsEscInterruptWatcher,
    _is_standalone_escape,
    create_interrupt_watcher,
)


class _FakeEscapeStream:
    def __init__(self, chunks: bytes) -> None:
        self._chunks = [bytes([value]) for value in chunks]

    def wait_for_byte(self, _timeout: float) -> bool:
        return bool(self._chunks)

    def read_byte(self) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    @property
    def remaining(self) -> list[bytes]:
        return list(self._chunks)


class _TestWatcher(EscInterruptWatcher):
    def __init__(self) -> None:
        super().__init__(poll_interval=0.001, sequence_timeout=0.001)
        self.restored = False

    def _get_stdin_fd(self) -> int | None:
        return 0

    def _is_tty(self, stdin_fd: int) -> bool:
        return True

    def _enter_cbreak_mode(self, stdin_fd: int) -> object:
        return object()

    def _restore_terminal_mode(self, stdin_fd: int, original_attrs: object | None) -> None:
        self.restored = True

    def _wait_for_input(self, stdin_fd: int, timeout: float) -> bool:
        if self._closed.is_set():
            return False
        time.sleep(min(timeout, 0.001))
        return False

    def _read_byte(self, stdin_fd: int) -> bytes:
        return b""


class _FakeWindowsConsole:
    def __init__(self, keys: list[str]) -> None:
        self._keys = keys

    def kbhit(self) -> bool:
        return bool(self._keys)

    def getwch(self) -> str:
        if not self._keys:
            return ""
        return self._keys.pop(0)


class _TestWindowsWatcher(WindowsEscInterruptWatcher):
    def __init__(self, console: _FakeWindowsConsole) -> None:
        super().__init__(poll_interval=0.001, sequence_timeout=0.001)
        self._console = console

    def _get_console(self):
        return self._console


def test_isolated_escape_triggers_interrupt() -> None:
    stream = _FakeEscapeStream(b"")

    interrupted = _is_standalone_escape(
        read_byte=stream.read_byte,
        wait_for_byte=stream.wait_for_byte,
        is_closed=lambda: False,
        sequence_timeout=0.001,
    )

    assert interrupted is True


def test_cpr_sequence_is_consumed_without_interrupt() -> None:
    stream = _FakeEscapeStream(b"[38;1R")

    interrupted = _is_standalone_escape(
        read_byte=stream.read_byte,
        wait_for_byte=stream.wait_for_byte,
        is_closed=lambda: False,
        sequence_timeout=0.001,
    )

    assert interrupted is False
    assert stream.remaining == []


def test_arrow_key_sequence_is_ignored() -> None:
    stream = _FakeEscapeStream(b"[A")

    interrupted = _is_standalone_escape(
        read_byte=stream.read_byte,
        wait_for_byte=stream.wait_for_byte,
        is_closed=lambda: False,
        sequence_timeout=0.001,
    )

    assert interrupted is False
    assert stream.remaining == []


def test_function_key_sequence_is_ignored() -> None:
    stream = _FakeEscapeStream(b"OP")

    interrupted = _is_standalone_escape(
        read_byte=stream.read_byte,
        wait_for_byte=stream.wait_for_byte,
        is_closed=lambda: False,
        sequence_timeout=0.001,
    )

    assert interrupted is False
    assert stream.remaining == []


def test_create_interrupt_watcher_enabled_on_windows_tty(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
    monkeypatch.setattr("os.isatty", lambda _fd: True)

    assert isinstance(create_interrupt_watcher(), WindowsEscInterruptWatcher)


def test_create_interrupt_watcher_disabled_without_tty(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
    monkeypatch.setattr("os.isatty", lambda _fd: False)

    assert create_interrupt_watcher() is None


@pytest.mark.asyncio
async def test_watcher_wait_exits_cleanly_after_close() -> None:
    watcher = _TestWatcher()
    wait_task = asyncio.create_task(watcher.wait())

    await asyncio.sleep(0.01)
    watcher.close()
    await asyncio.wait_for(wait_task, timeout=0.2)

    assert watcher.restored is True


@pytest.mark.asyncio
async def test_windows_watcher_standalone_escape_triggers_interrupt() -> None:
    watcher = _TestWindowsWatcher(_FakeWindowsConsole(["\x1b"]))

    await asyncio.wait_for(watcher.wait(), timeout=0.2)
