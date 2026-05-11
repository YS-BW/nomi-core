import inspect


def test_sanitize_persisted_blocks_truncate_text_shadowing_regression() -> None:
    """Regression: avoid bool param shadowing imported truncate_text.

    Buggy behavior (historical):
    - loop.py imports `truncate_text` from helpers
    - `_sanitize_persisted_blocks(..., truncate_text: bool=...)` uses same name
    - when called with `truncate_text=True`, function body executes `truncate_text(text, ...)`
      which resolves to bool and raises `TypeError: 'bool' object is not callable`.

    This test asserts the fixed API exists and truncation works without raising.
    """

    from types import SimpleNamespace

    from nomi.agent.execution.processor import TurnProcessor
    from nomi.agent.loop import AgentLoop

    sig = inspect.signature(AgentLoop._sanitize_persisted_blocks)
    assert "should_truncate_text" in sig.parameters
    assert "truncate_text" not in sig.parameters

    dummy_loop = SimpleNamespace(max_tool_result_chars=5)
    processor = TurnProcessor(dummy_loop)
    content = [{"type": "text", "text": "0123456789"}]

    out = processor.sanitize_persisted_blocks(content, should_truncate_text=True)
    assert isinstance(out, list)
    assert out and out[0]["type"] == "text"
    assert isinstance(out[0]["text"], str)
    assert out[0]["text"] != content[0]["text"]
