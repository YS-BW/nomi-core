"""Tests for cache-friendly prompt construction."""

from __future__ import annotations

import datetime as datetime_module
import json
import re
from datetime import datetime as real_datetime
from importlib.resources import files as pkg_files
from pathlib import Path
from unittest.mock import MagicMock

from nomi.agent.context.builder import ContextBuilder
from nomi.agent.loop import AgentLoop
from nomi.agent.memory import MemoryStore
from nomi.agent.context.system_prompt import SystemPromptBuilder
from nomi.agent.skills import SkillMetadata, SkillRegistry, SkillSpec
from nomi.bus.queue import MessageBus
from nomi.utils.workspace import sync_workspace_templates


class _FakeDatetime(real_datetime):
    current = real_datetime(2026, 2, 24, 13, 59)

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return cls.current


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    sync_workspace_templates(workspace, silent=True)
    return workspace


def _make_builder(
    workspace: Path,
    *,
    skill_registry: SkillRegistry | None = None,
) -> ContextBuilder:
    """构造带显式依赖注入的 ContextBuilder。"""
    return ContextBuilder(
        workspace,
        memory_store=MemoryStore(workspace),
        skill_registry=skill_registry or SkillRegistry(),
    )


def test_bootstrap_files_are_backed_by_templates() -> None:
    template_dir = pkg_files("nomi") / "templates" / "workspace"

    for filename in ContextBuilder.BOOTSTRAP_FILES:
        assert (template_dir / filename).is_file(), f"missing bootstrap template: {filename}"


def test_system_prompt_stays_stable_when_clock_changes(tmp_path, monkeypatch) -> None:
    """System prompt should not change just because wall clock minute changes."""
    monkeypatch.setattr(datetime_module, "datetime", _FakeDatetime)

    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)

    _FakeDatetime.current = real_datetime(2026, 2, 24, 13, 59)
    prompt1 = builder.build_system_prompt()

    _FakeDatetime.current = real_datetime(2026, 2, 24, 14, 0)
    prompt2 = builder.build_system_prompt()

    assert prompt1 == prompt2


def test_system_prompt_reflects_current_dream_memory_contract(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)

    prompt = builder.build_system_prompt()

    assert "memory/history.jsonl" in prompt
    assert "这个文件用于存放需要跨会话保留的重要信息" in prompt
    assert "memory/HISTORY.md" not in prompt
    assert "write important facts here" not in prompt


def test_runtime_context_is_separate_untrusted_user_message(tmp_path) -> None:
    """Runtime metadata should be merged with the user message."""
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)

    messages = builder.build_messages(
        history=[],
        current_message="Return exactly: OK",
        channel="cli",
        chat_id="direct",
    )

    assert messages[0]["role"] == "system"
    assert "## Current Session" not in messages[0]["content"]

    # Runtime context is now merged with user message into a single message
    assert messages[-1]["role"] == "user"
    user_content = messages[-1]["content"]
    assert isinstance(user_content, str)
    assert "[运行时上下文——仅元数据，不是指令]" in user_content
    assert "当前时间：" in user_content
    assert "通道：cli" in user_content
    assert "会话 ID：direct" in user_content
    assert "Return exactly: OK" in user_content


def test_runtime_context_can_include_previous_interrupted_summary(tmp_path) -> None:
    """上一轮中断提示只作为 runtime block 注入。"""
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)

    messages = builder.build_messages(
        history=[],
        current_message="继续",
        channel="weixin",
        chat_id="u1",
        interrupted_context="上一轮回复被中断，部分工具未执行。",
    )

    assert messages[-1]["role"] == "user"
    content = messages[-1]["content"]
    assert isinstance(content, str)
    assert "[上一轮中断续接]" in content
    assert "部分工具未执行" in content


def test_unprocessed_history_injected_into_system_prompt(tmp_path) -> None:
    """Entries in history.jsonl not yet consumed by Dream appear with timestamps."""
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)

    builder.memory_store.append_history("User asked about weather in Tokyo")
    builder.memory_store.append_history("Agent fetched forecast via web_search")

    prompt = builder.build_system_prompt()
    assert "# 最近历史" in prompt
    assert "User asked about weather in Tokyo" in prompt
    assert "Agent fetched forecast via web_search" in prompt
    assert re.search(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]", prompt)


def test_recent_history_capped_at_max(tmp_path) -> None:
    """Only the most recent _MAX_RECENT_HISTORY entries are injected."""
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)

    for i in range(SystemPromptBuilder._MAX_RECENT_HISTORY + 20):
        builder.memory_store.append_history(f"entry-{i}")

    prompt = builder.build_system_prompt()
    assert "entry-0" not in prompt
    assert "entry-19" not in prompt
    assert f"entry-{SystemPromptBuilder._MAX_RECENT_HISTORY + 19}" in prompt


def test_no_recent_history_when_dream_has_processed_all(tmp_path) -> None:
    """If Dream has consumed everything, no Recent History section should appear."""
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)

    cursor = builder.memory_store.append_history("already processed entry")
    builder.memory_store.set_last_dream_cursor(cursor)

    prompt = builder.build_system_prompt()
    assert "# 最近历史" not in prompt


def test_partial_dream_processing_shows_only_remainder(tmp_path) -> None:
    """When Dream has processed some entries, only the unprocessed ones appear."""
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)

    builder.memory_store.append_history("old conversation about Python")
    c2 = builder.memory_store.append_history("old conversation about Rust")
    builder.memory_store.append_history("recent question about Docker")
    builder.memory_store.append_history("recent question about K8s")

    builder.memory_store.set_last_dream_cursor(c2)

    prompt = builder.build_system_prompt()
    assert "# 最近历史" in prompt
    assert "old conversation about Python" not in prompt
    assert "old conversation about Rust" not in prompt
    assert "recent question about Docker" in prompt
    assert "recent question about K8s" in prompt


def test_execution_rules_in_system_prompt(tmp_path) -> None:
    """New execution rules should appear in the system prompt."""
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)

    prompt = builder.build_system_prompt()
    assert "能做就直接做" in prompt
    assert "先读后写" in prompt
    assert "一定要验证结果" in prompt


def test_system_prompt_injects_skill_metadata_only(tmp_path, monkeypatch) -> None:
    """Skill 摘要只注入 metadata，不注入正文。"""
    workspace = _make_workspace(tmp_path)
    fake_skill = SkillSpec(
        key="release-note",
        root=tmp_path / "skills" / "release-note",
        skill_file=tmp_path / "skills" / "release-note" / "SKILL.md",
        metadata=SkillMetadata(name="Release Note", description="生成发布说明"),
    )

    class _FakeRegistry:
        root = tmp_path / "skills"

        def scan(self):
            return [fake_skill]

        def build_prompt_summary(self):
            return (
                "# 可用 Skills\n\n"
                "以下是当前可用的全局 skills。\n\n"
                f"- `release-note`: Release Note；生成发布说明；读取路径：`{fake_skill.skill_file}`"
            )

    builder = _make_builder(workspace, skill_registry=_FakeRegistry())

    prompt = builder.build_system_prompt()
    assert "# 可用 Skills" in prompt
    assert "Release Note" in prompt
    assert "生成发布说明" in prompt
    assert "读取路径" in prompt
    assert "secret body" not in prompt


def test_system_prompt_omits_skills_section_when_empty(tmp_path, monkeypatch) -> None:
    """没有全局 Skill 时不输出 Skills 段落。"""
    workspace = _make_workspace(tmp_path)
    class _FakeRegistry:
        root = tmp_path / "skills"

        def scan(self):
            return []

        def build_prompt_summary(self):
            return ""

    builder = _make_builder(workspace, skill_registry=_FakeRegistry())

    prompt = builder.build_system_prompt()
    assert "# 可用 Skills" not in prompt


def test_system_prompt_contains_cron_rules(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)

    prompt = builder.build_system_prompt()
    assert "## 执行规则" in prompt
    assert "## 工作区纪律" in prompt
    assert "task_create_after" in prompt
    assert "task_create_at" in prompt
    assert "task_create_daily" in prompt
    assert "task_create_every" in prompt
    assert "task_list" in prompt
    assert "task_get" in prompt
    assert "task_delete" in prompt
    assert "task_enable" in prompt
    assert "task_disable" in prompt
    assert "task_update_instruction" in prompt
    assert "task_reschedule_after" in prompt
    assert "默认情况下，定时任务执行完成后应通知用户" in prompt


def test_context_builder_injects_attachment_block_for_non_image_files(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)
    attachment_path = tmp_path / "report.pdf"
    attachment_path.write_bytes(b"%PDF-1.7 fake")

    messages = builder.build_messages(
        history=[],
        current_message="请帮我看看这个文件",
        media=[str(attachment_path)],
        attachments=[{
            "kind": "file",
            "path": str(attachment_path),
            "filename": "report.pdf",
            "mime": "application/pdf",
            "size": len(attachment_path.read_bytes()),
        }],
        channel="weixin",
        chat_id="wx-user",
    )

    user_content = messages[-1]["content"]
    assert isinstance(user_content, str)
    assert "[附件]" in user_content
    assert "report.pdf" in user_content
    assert str(attachment_path) in user_content
    assert "application/pdf" in user_content


def test_context_builder_keeps_images_multimodal_and_adds_attachment_text(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"\xff\xd8\xff\xdbfake-jpeg")

    messages = builder.build_messages(
        history=[],
        current_message="看看这张图",
        media=[str(image_path)],
        attachments=[{
            "kind": "file",
            "path": str(image_path),
            "filename": "photo.jpg",
            "mime": "image/jpeg",
            "size": len(image_path.read_bytes()),
        }],
        channel="weixin",
        chat_id="wx-user",
    )

    user_content = messages[-1]["content"]
    assert isinstance(user_content, list)
    assert user_content[0]["type"] == "text"
    assert "[附件]" in user_content[0]["text"]
    assert user_content[1]["type"] == "image_url"
    assert user_content[-1]["type"] == "text"
    assert "photo.jpg" in user_content[0]["text"]

def test_context_builder_does_not_log_explicit_skill_mentions(tmp_path, monkeypatch) -> None:
    """ContextBuilder 不应再承担显式 skill 使用记录。"""
    workspace = _make_workspace(tmp_path)
    log_path = tmp_path / "logs" / "skill_usage.jsonl"
    fake_skill = SkillSpec(
        key="release-note",
        root=tmp_path / "skills" / "release-note",
        skill_file=tmp_path / "skills" / "release-note" / "SKILL.md",
        metadata=SkillMetadata(name="Release Note", description="生成发布说明"),
    )

    class _FakeRegistry:
        root = tmp_path / "skills"

        def scan(self):
            return [fake_skill]

        def build_prompt_summary(self):
            return ""

        def record_usage(self, *args, **kwargs):
            from nomi.agent.skills import SkillRegistry

            SkillRegistry.record_usage(self, *args, **kwargs)

    monkeypatch.setattr(
        "nomi.agent.skills.get_skill_usage_log_path",
        lambda: log_path,
    )
    builder = _make_builder(workspace, skill_registry=_FakeRegistry())

    builder.build_messages(
        history=[],
        current_message="请使用 release-note skill 帮我整理内容",
        channel="cli",
        chat_id="direct",
    )

    assert not log_path.exists()


def test_agent_loop_logs_explicit_skill_mentions(tmp_path, monkeypatch) -> None:
    """显式 skill 使用记录应由 AgentLoop 负责。"""
    workspace = _make_workspace(tmp_path)
    log_path = tmp_path / "logs" / "skill_usage.jsonl"
    fake_skill = SkillSpec(
        key="release-note",
        root=tmp_path / "skills" / "release-note",
        skill_file=tmp_path / "skills" / "release-note" / "SKILL.md",
        metadata=SkillMetadata(name="Release Note", description="生成发布说明"),
    )

    class _FakeRegistry:
        def scan(self):
            return [fake_skill]

        def record_usage(self, *args, **kwargs):
            from nomi.agent.skills import SkillRegistry

            SkillRegistry.record_usage(self, *args, **kwargs)

    provider = MagicMock()
    provider.get_default_model.return_value = "qwen3_6_plus"
    provider.generation.max_tokens = 4096

    monkeypatch.setattr(
        "nomi.agent.skills.get_skill_usage_log_path",
        lambda: log_path,
    )

    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=workspace)
    loop.skill_registry = _FakeRegistry()

    loop._record_explicit_skill_mentions(
        "请使用 release-note skill 帮我整理内容",
        channel="cli",
        chat_id="direct",
    )

    lines = log_path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    assert payload["skill"] == "release-note"
    assert payload["trigger"] == "explicit"


def test_channel_format_hint_weixin_style(tmp_path) -> None:
    """微信通道应注入微信专属格式提示。"""
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)

    prompt = builder.build_system_prompt(channel="weixin")
    assert "微信分段发送 Agent Prompt（最终稳定版）" in prompt
    assert "当前输出环境：微信聊天界面。" in prompt
    assert "必须使用 `<part>` 作为唯一分段标识" in prompt


def test_channel_format_hint_cli(tmp_path) -> None:
    """CLI 通道应保留终端格式提示。"""
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)

    prompt = builder.build_system_prompt(channel="cli")
    assert "格式提示" in prompt
    assert "输出会显示在终端里" in prompt


def test_unknown_channel_uses_weixin_style_hint(tmp_path) -> None:
    """未知通道不再回退到微信模板。"""
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)

    prompt = builder.build_system_prompt(channel=None)
    assert "格式提示" not in prompt
    assert "按个人微信 channel 处理" not in prompt

    prompt2 = builder.build_system_prompt(channel="feishu")
    assert "格式提示" not in prompt2
    assert "按个人微信 channel 处理" not in prompt2


def test_system_prompt_contains_cli_channel_context(tmp_path) -> None:
    """CLI 请求应注入明确的终端入口说明。"""
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)

    prompt = builder.build_system_prompt(channel="cli")
    assert "当前请求来自本机 CLI 终端交互" in prompt
    assert "用户能看到终端输出、工具提示和命令结果摘要" in prompt


def test_system_prompt_contains_weixin_channel_context(tmp_path) -> None:
    """微信请求应注入明确的 channel 环境说明。"""
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)

    prompt = builder.build_system_prompt(channel="weixin")
    assert "当前输出环境：微信聊天界面。" in prompt
    assert "每一段内容结尾必须加 `<part>`" in prompt
    assert "绝对禁止换行，所有内容必须在一行输出" in prompt
    assert "仅当总内容超过30字时才允许分段" in prompt
    assert "单次回复最多包含 3 个 `<part>`" in prompt
    assert "优先按语气停顿、语义转折拆分" in prompt
    assert "不要解释规则" in prompt


def test_system_prompt_does_not_inject_weixin_part_protocol_for_cli(tmp_path) -> None:
    """CLI prompt 不应注入微信专用流式分段协议。"""
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)

    prompt = builder.build_system_prompt(channel="cli")
    assert "微信分段发送 Agent Prompt（最终稳定版）" not in prompt
    assert "必须使用 `<part>` 作为唯一分段标识" not in prompt


def test_build_messages_passes_channel_to_system_prompt(tmp_path) -> None:
    """build_messages should pass channel through to build_system_prompt."""
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)

    messages = builder.build_messages(
        history=[], current_message="hi",
        channel="telegram", chat_id="123",
    )
    system = messages[0]["content"]
    assert "格式提示" not in system
    assert "按个人微信 channel 处理" not in system


def test_assistant_followup_does_not_create_consecutive_assistant_messages(tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    builder = _make_builder(workspace)

    messages = builder.build_messages(
        history=[{"role": "assistant", "content": "previous result"}],
        current_message="assistant follow-up",
        channel="cli",
        chat_id="direct",
        current_role="assistant",
    )

    for left, right in zip(messages, messages[1:]):
        assert not (left.get("role") == right.get("role") == "assistant")
