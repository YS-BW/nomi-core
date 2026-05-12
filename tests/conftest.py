"""pytest 级测试隔离。"""

from __future__ import annotations

import pytest


def pytest_configure(config):
    """注册本仓自定义 pytest marker。"""
    config.addinivalue_line(
        "markers",
        "uses_real_default_instance_root: test intentionally asserts the real ~/.nomi default",
    )


@pytest.fixture(autouse=True)
def reset_instance_context_between_tests(request, tmp_path, monkeypatch):
    """每个测试前后隔离实例与配置全局上下文，避免读写真实 `~/.nomi`。"""
    from nomi.config import instance as instance_module
    from nomi.config import loader as loader_module

    instance_module._current_instance_name = None  # noqa: SLF001
    instance_module._current_instance_root = None  # noqa: SLF001
    loader_module._current_config_path = None  # noqa: SLF001
    if request.node.get_closest_marker("uses_real_default_instance_root") is None:
        isolated_root = tmp_path / ".nomi-test"
        monkeypatch.setattr(
            "nomi.config.instance.get_default_instance_root",
            lambda: isolated_root,
        )
    try:
        yield
    finally:
        instance_module._current_instance_name = None  # noqa: SLF001
        instance_module._current_instance_root = None  # noqa: SLF001
        loader_module._current_config_path = None  # noqa: SLF001
