from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nomi.agent.context.builder import ContextBuilder
from nomi.agent.loop import AgentLoop
from nomi.agent.execution.turn_journal import ToolJournalEntry, TurnJournalRecord, attach_running_journal_metadata
from nomi.bus.queue import MessageBus
from nomi.providers.base import LLMProvider
from nomi.session.manager import Session


def _mk_loop(tmp_path: Path) -> AgentLoop:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.generation = SimpleNamespace(max_tokens=4096)
    with patch("nomi.agent.loop.register_default_tools"):
        return AgentLoop(
            bus=MessageBus(),
            provider=provider,
            workspace=tmp_path,
        )


def test_save_turn_skips_multimodal_user_when_only_runtime_context() -> None:
    loop = _mk_loop(Path("/tmp/nomi-test-runtime-only"))
    session = Session(key="test:runtime-only")
    runtime = ContextBuilder._RUNTIME_CONTEXT_TAG + "\n当前时间：now (UTC)"

    loop._save_turn(
        session,
        [{"role": "user", "content": [{"type": "text", "text": runtime}]}],
        skip=0,
    )
    assert session.messages == []


def test_save_turn_keeps_image_placeholder_with_path_after_runtime_strip() -> None:
    loop = _mk_loop(Path("/tmp/nomi-test-image"))
    session = Session(key="test:image")
    runtime = ContextBuilder._RUNTIME_CONTEXT_TAG + "\n当前时间：now (UTC)"

    loop._save_turn(
        session,
        [{
            "role": "user",
            "content": [
                {"type": "text", "text": runtime},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}, "_meta": {"path": "/media/feishu/photo.jpg"}},
            ],
        }],
        skip=0,
    )
    assert session.messages[0]["content"] == [{"type": "text", "text": "[image: /media/feishu/photo.jpg]"}]


def test_save_turn_keeps_image_placeholder_without_meta() -> None:
    loop = _mk_loop(Path("/tmp/nomi-test-image-no-meta"))
    session = Session(key="test:image-no-meta")
    runtime = ContextBuilder._RUNTIME_CONTEXT_TAG + "\n当前时间：now (UTC)"

    loop._save_turn(
        session,
        [{
            "role": "user",
            "content": [
                {"type": "text", "text": runtime},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        }],
        skip=0,
    )
    assert session.messages[0]["content"] == [{"type": "text", "text": "[image]"}]


def test_save_turn_keeps_tool_results_under_16k() -> None:
    loop = _mk_loop(Path("/tmp/nomi-test-tool-result"))
    session = Session(key="test:tool-result")
    content = "x" * 12_000

    loop._save_turn(
        session,
        [{"role": "tool", "tool_call_id": "call_1", "name": "read_file", "content": content}],
        skip=0,
    )

    assert session.messages[0]["content"] == content


def test_restore_runtime_checkpoint_rehydrates_completed_and_pending_tools() -> None:
    loop = _mk_loop(Path("/tmp/nomi-test-checkpoint"))
    session = Session(
        key="test:checkpoint",
        metadata={
            AgentLoop._RUNTIME_CHECKPOINT_KEY: {
                "assistant_message": {
                    "role": "assistant",
                    "content": "working",
                    "tool_calls": [
                        {
                            "id": "call_done",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        },
                        {
                            "id": "call_pending",
                            "type": "function",
                            "function": {"name": "exec", "arguments": "{}"},
                        },
                    ],
                },
                "completed_tool_results": [
                    {
                        "role": "tool",
                        "tool_call_id": "call_done",
                        "name": "read_file",
                        "content": "ok",
                    }
                ],
                "pending_tool_calls": [
                    {
                        "id": "call_pending",
                        "type": "function",
                        "function": {"name": "exec", "arguments": "{}"},
                    }
                ],
            }
        },
    )

    restored = loop._restore_runtime_checkpoint(session)

    assert restored is True
    assert session.metadata.get(AgentLoop._RUNTIME_CHECKPOINT_KEY) is None
    assert session.messages[0]["role"] == "assistant"
    assert session.messages[1]["tool_call_id"] == "call_done"
    assert session.messages[2]["tool_call_id"] == "call_pending"
    assert session.messages[2]["content"] == "Interrupted: tool execution stopped before completion."


def test_restore_runtime_checkpoint_dedupes_overlapping_tail() -> None:
    loop = _mk_loop(Path("/tmp/nomi-test-checkpoint-overlap"))
    session = Session(
        key="test:checkpoint-overlap",
        messages=[
            {
                "role": "assistant",
                "content": "working",
                "tool_calls": [
                    {
                        "id": "call_done",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    },
                    {
                        "id": "call_pending",
                        "type": "function",
                        "function": {"name": "exec", "arguments": "{}"},
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_done",
                "name": "read_file",
                "content": "ok",
            },
        ],
        metadata={
            AgentLoop._RUNTIME_CHECKPOINT_KEY: {
                "assistant_message": {
                    "role": "assistant",
                    "content": "working",
                    "tool_calls": [
                        {
                            "id": "call_done",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        },
                        {
                            "id": "call_pending",
                            "type": "function",
                            "function": {"name": "exec", "arguments": "{}"},
                        },
                    ],
                },
                "completed_tool_results": [
                    {
                        "role": "tool",
                        "tool_call_id": "call_done",
                        "name": "read_file",
                        "content": "ok",
                    }
                ],
                "pending_tool_calls": [
                    {
                        "id": "call_pending",
                        "type": "function",
                        "function": {"name": "exec", "arguments": "{}"},
                    }
                ],
            }
        },
    )

    restored = loop._restore_runtime_checkpoint(session)

    assert restored is True
    assert session.metadata.get(AgentLoop._RUNTIME_CHECKPOINT_KEY) is None
    assert len(session.messages) == 3
    assert session.messages[0]["role"] == "assistant"
    assert session.messages[1]["tool_call_id"] == "call_done"
    assert session.messages[2]["tool_call_id"] == "call_pending"
    assert session.messages[2]["content"] == "Interrupted: tool execution stopped before completion."


def test_restore_turn_journal_rehydrates_visible_text_and_tool_states() -> None:
    loop = _mk_loop(Path("/tmp/nomi-test-turn-journal"))
    session = Session(key="test:turn-journal")
    journal = TurnJournalRecord(
        turn_id="turn_001",
        session_key=session.key,
        status="running",
        user_message={"role": "user", "content": "看看当前项目有什么"},
        visible_assistant_text="已经发给用户的正文",
        assistant_message={
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_done",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                },
                {
                    "id": "call_skip",
                    "type": "function",
                    "function": {"name": "exec", "arguments": "{}"},
                },
            ],
        },
        tool_calls=[
            {
                "id": "call_done",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            },
            {
                "id": "call_skip",
                "type": "function",
                "function": {"name": "exec", "arguments": "{}"},
            },
        ],
        tool_entries=[
            ToolJournalEntry(
                tool_call_id="call_done",
                name="read_file",
                arguments={},
                status="succeeded",
                result="ok",
            ),
            ToolJournalEntry(
                tool_call_id="call_skip",
                name="exec",
                arguments={},
                status="planned",
            ),
        ],
    )
    loop.turn_journals.save(journal)
    attach_running_journal_metadata(session, journal)

    restored = loop._restore_runtime_checkpoint(session)

    assert restored is True
    assert session.messages[0]["role"] == "user"
    assert session.messages[0]["content"] == "看看当前项目有什么"
    assert session.messages[1]["role"] == "assistant"
    assert session.messages[1]["content"] == "已经发给用户的正文"
    assert session.messages[2]["content"] == "ok"
    assert session.messages[3]["content"] == "Skipped: tool execution did not start before interruption."
    assert session.metadata["previous_turn_interrupted"]["turn_id"] == "turn_001"


def test_finalize_completed_turn_journal_deletes_file_and_metadata() -> None:
    loop = _mk_loop(Path("/tmp/nomi-test-turn-journal-finish"))
    session = Session(key="test:turn-journal-finish")
    journal = TurnJournalRecord(
        turn_id="turn_finish",
        session_key=session.key,
        status="running",
        visible_assistant_text="半成品",
        assistant_message={"role": "assistant", "content": "半成品"},
    )
    loop.turn_journals.save(journal)
    attach_running_journal_metadata(session, journal)

    loop._turns.finalize_completed_turn_journal(session, "最终回复")

    assert session.metadata.get("turn_journal") is None
    assert loop.turn_journals.load(session.key, journal.turn_id) is None
