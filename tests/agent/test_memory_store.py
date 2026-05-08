"""Tests for the restructured MemoryStore — pure file I/O layer."""

import json
from pathlib import Path

import pytest

from nomi.agent.memory import MemoryStore
from nomi.agent.memory.store import UserProfileCandidate


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path)


class TestMemoryStoreBasicIO:
    def test_read_memory_returns_empty_when_missing(self, store):
        assert store.read_memory() == ""

    def test_write_and_read_memory(self, store):
        store.write_memory("hello")
        assert store.read_memory() == "hello"

    def test_read_soul_returns_empty_when_missing(self, store):
        assert store.read_soul() == ""

    def test_write_and_read_soul(self, store):
        store.write_soul("soul content")
        assert store.read_soul() == "soul content"

    def test_read_user_returns_empty_when_missing(self, store):
        assert store.read_user() == ""

    def test_write_and_read_user(self, store):
        store.write_user("user content")
        assert store.read_user() == "user content"

    def test_get_memory_context_returns_empty_when_missing(self, store):
        assert store.get_memory_context() == ""

    def test_get_memory_context_returns_formatted_content(self, store):
        store.write_memory("important fact")
        ctx = store.get_memory_context()
        assert "长期记忆" in ctx
        assert "important fact" in ctx


class TestHistoryWithCursor:
    def test_append_history_returns_cursor(self, store):
        cursor = store.append_history("event 1")
        assert cursor == 1
        cursor2 = store.append_history("event 2")
        assert cursor2 == 2

    def test_append_history_includes_cursor_in_file(self, store):
        store.append_history("event 1")
        content = store.read_file(store.history_file)
        data = json.loads(content)
        assert data["cursor"] == 1

    def test_cursor_persists_across_appends(self, store):
        store.append_history("event 1")
        store.append_history("event 2")
        cursor = store.append_history("event 3")
        assert cursor == 3

    def test_read_unprocessed_history(self, store):
        store.append_history("event 1")
        store.append_history("event 2")
        store.append_history("event 3")
        entries = store.read_unprocessed_history(since_cursor=1)
        assert len(entries) == 2
        assert entries[0]["cursor"] == 2

    def test_read_unprocessed_history_returns_all_when_cursor_zero(self, store):
        store.append_history("event 1")
        store.append_history("event 2")
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 2

    def test_compact_history_drops_oldest(self, tmp_path):
        store = MemoryStore(tmp_path, max_history_entries=2)
        store.append_history("event 1")
        store.append_history("event 2")
        store.append_history("event 3")
        store.append_history("event 4")
        store.append_history("event 5")
        store.compact_history()
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 2
        assert entries[0]["cursor"] in {4, 5}


class TestDreamCursor:
    def test_initial_cursor_is_zero(self, store):
        assert store.get_last_dream_cursor() == 0

    def test_set_and_get_cursor(self, store):
        store.set_last_dream_cursor(5)
        assert store.get_last_dream_cursor() == 5

    def test_cursor_persists(self, store):
        store.set_last_dream_cursor(3)
        store2 = MemoryStore(store.workspace)
        assert store2.get_last_dream_cursor() == 3


class TestLegacyHistoryCleanup:
    def test_read_unprocessed_history_handles_entries_without_cursor(self, store):
        """JSONL entries with cursor=1 are correctly parsed and returned."""
        store.history_file.write_text(
            '{"cursor": 1, "timestamp": "2026-03-30 14:30", "content": "Old event"}\n',
            encoding="utf-8")
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert entries[0]["cursor"] == 1

    def test_init_removes_legacy_history_and_backup_files(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "HISTORY.md").write_text("legacy", encoding="utf-8")
        (memory_dir / "HISTORY.md.bak").write_text("backup", encoding="utf-8")
        (memory_dir / "HISTORY.md.bak.2").write_text("backup2", encoding="utf-8")

        MemoryStore(tmp_path)

        assert not (memory_dir / "HISTORY.md").exists()
        assert not (memory_dir / "HISTORY.md.bak").exists()
        assert not (memory_dir / "HISTORY.md.bak.2").exists()

    def test_init_keeps_current_history_jsonl_while_removing_legacy_files(self, tmp_path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        history_file = memory_dir / "history.jsonl"
        history_file.write_text(
            '{"cursor": 7, "timestamp": "2026-04-01 12:00", "content": "existing"}\n',
            encoding="utf-8",
        )
        (memory_dir / "HISTORY.md").write_text("legacy", encoding="utf-8")
        (memory_dir / "HISTORY.md.bak").write_text("backup", encoding="utf-8")

        store = MemoryStore(tmp_path)

        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert entries[0]["cursor"] == 7
        assert entries[0]["content"] == "existing"
        assert not (memory_dir / "HISTORY.md").exists()
        assert not (memory_dir / "HISTORY.md.bak").exists()


class TestDreamHistoryOwnerApi:
    def test_show_dream_version_reports_never_run_before_init(self, store):
        result = store.show_dream_version()

        assert result.status == "never_run"

    def test_list_and_show_dream_versions_after_commit(self, store):
        store.git.init()
        store.write_soul("updated soul")
        sha = store.git.auto_commit("dream: latest, 1 change(s)")

        versions = store.list_dream_versions()
        result = store.show_dream_version()

        assert versions[0].sha == sha
        assert result.status == "ok"
        assert result.commit is not None
        assert result.commit.sha == sha
        assert "SOUL.md" in result.changed_files

    def test_restore_dream_version_returns_new_safe_commit(self, store):
        store.git.init()
        store.write_soul("updated soul")
        sha = store.git.auto_commit("dream: latest, 1 change(s)")

        result = store.restore_dream_version(sha)

        assert result.status == "ok"
        assert result.new_sha is not None
        assert "SOUL.md" in result.changed_files


class TestUserProfileCandidates:
    def test_upsert_candidate_persists_independent_state_file(self, store):
        candidate = UserProfileCandidate(
            id="",
            status="pending",
            created_at="",
            updated_at="",
            session_key="weixin:test",
            source_text="我更喜欢简洁一点",
            field="沟通偏好.回复风格",
            operation="set",
            value="直接简洁",
            old_value=None,
            reason="用户明确表达",
            confidence=0.9,
        )

        saved = store.upsert_user_profile_candidate(candidate)

        assert saved.id == "user_prof_0001"
        payload = json.loads(Path(store.user_profile_candidates_file).read_text(encoding="utf-8"))
        assert payload["version"] == 1
        assert payload["items"][0]["field"] == "沟通偏好.回复风格"

    def test_upsert_same_field_and_value_merges_pending_candidate(self, store):
        first = store.upsert_user_profile_candidate(
            UserProfileCandidate(
                id="",
                status="pending",
                created_at="",
                updated_at="",
                session_key="cli:direct",
                source_text="我喜欢简洁",
                field="沟通偏好.回复风格",
                operation="set",
                value="直接简洁",
                old_value=None,
                reason="first",
                confidence=0.4,
            )
        )
        second = store.upsert_user_profile_candidate(
            UserProfileCandidate(
                id="",
                status="pending",
                created_at="",
                updated_at="",
                session_key="cli:direct",
                source_text="你直接一点就行",
                field="沟通偏好.回复风格",
                operation="set",
                value="直接简洁",
                old_value=None,
                reason="second",
                confidence=0.9,
            )
        )

        assert first.id == second.id
        pending = store.list_pending_user_profile_candidates(session_key="cli:direct")
        assert len(pending) == 1
        assert pending[0].confidence == 0.9
        assert pending[0].reason == "second"

    def test_apply_candidate_updates_user_markdown(self, store):
        store.ensure_user_profile_initialized()
        candidate = store.upsert_user_profile_candidate(
            UserProfileCandidate(
                id="",
                status="pending",
                created_at="",
                updated_at="",
                session_key="cli:direct",
                source_text="我更喜欢中文",
                field="基本信息.常用语言",
                operation="set",
                value="中文",
                old_value=None,
                reason="用户明确表达",
                confidence=0.8,
            )
        )

        applied = store.apply_user_profile_candidate(candidate.id)

        assert applied is not None
        assert applied.status == "applied"
        content = store.read_user()
        assert "- 常用语言：中文" in content

    def test_reject_candidate_marks_status(self, store):
        candidate = store.upsert_user_profile_candidate(
            UserProfileCandidate(
                id="",
                status="pending",
                created_at="",
                updated_at="",
                session_key="cli:direct",
                source_text="我不喜欢太长",
                field="沟通偏好.长短偏好",
                operation="set",
                value="简短直接",
                old_value=None,
                reason="用户明确表达",
                confidence=0.7,
            )
        )

        rejected = store.reject_user_profile_candidate(candidate.id)

        assert rejected is not None
        assert rejected.status == "rejected"

    def test_candidates_persist_across_store_reloads(self, store):
        store.upsert_user_profile_candidate(
            UserProfileCandidate(
                id="",
                status="pending",
                created_at="",
                updated_at="",
                session_key="weixin:test",
                source_text="我喜欢分步骤",
                field="沟通偏好.回复方式偏好",
                operation="set",
                value="分步骤",
                old_value=None,
                reason="用户明确表达",
                confidence=0.85,
            )
        )

        store2 = MemoryStore(store.workspace)

        pending = store2.list_pending_user_profile_candidates(session_key="weixin:test")
        assert len(pending) == 1
        assert pending[0].value == "分步骤"
