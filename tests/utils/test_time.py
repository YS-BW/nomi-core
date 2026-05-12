from __future__ import annotations

from nomi.utils.time import current_time_str


def test_current_time_str_defaults_to_asia_shanghai() -> None:
    result = current_time_str()
    assert "Asia/Shanghai" in result
