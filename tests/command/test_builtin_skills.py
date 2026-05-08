from __future__ import annotations

from types import SimpleNamespace

import pytest

from nomi.bus.events import InboundMessage
from nomi.command.handlers.builtin import build_help_text, register_builtin_commands
from nomi.command.handlers.skills import cmd_skill_manage
from nomi.command.router import CommandContext, CommandRouter
from nomi.agent.memory.store import UserProfileCandidate


def _make_ctx(raw: str) -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=raw)
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, loop=SimpleNamespace())


@pytest.mark.asyncio
async def test_skill_command_lists_installed_skills(monkeypatch) -> None:
    fake_items = [
        {
            "key": "minimax-docx",
            "name": "minimax-docx",
            "description": "处理 Word 文档",
            "skill_file": "/tmp/minimax-docx/SKILL.md",
        },
        {
            "key": "release-note",
            "name": "Release Note",
            "description": "生成发布说明",
            "skill_file": "/tmp/release-note/SKILL.md",
        },
    ]

    class _FakeRegistry:
        def list_status(self):
            return fake_items

    monkeypatch.setattr(
        "nomi.command.handlers.skills.SkillRegistry",
        lambda: _FakeRegistry(),
    )

    ctx = _make_ctx("/skill list")
    ctx.args = "list"
    out = await cmd_skill_manage(ctx)
    assert "## Skills" in out.content
    assert "`minimax-docx` minimax-docx" in out.content
    assert "`release-note` Release Note" in out.content


def test_help_text_contains_new_skills_commands() -> None:
    help_text = build_help_text()
    assert "/skill list" in help_text
    assert "/skill install <source>" in help_text
    assert "/skill uninstall <name>" in help_text
    assert "/skill —" not in help_text
    assert "/task" not in help_text
    assert "/stop" not in help_text
    assert "/user-review" in help_text
    assert "/user-apply <id>" in help_text
    assert "/user-reject <id>" in help_text
    assert "/user-show" in help_text


@pytest.mark.asyncio
async def test_skill_manage_install_calls_manager(monkeypatch) -> None:
    install_calls: list[str] = []

    class _FakeManager:
        def install(self, source: str):
            install_calls.append(source)
            return True, f"已安装 skill：`{source}`。"

    monkeypatch.setattr(
        "nomi.command.handlers.skills.SkillManager",
        lambda: _FakeManager(),
    )

    ctx = _make_ctx('/skill install "/tmp/demo skill"')
    ctx.args = 'install "/tmp/demo skill"'
    out = await cmd_skill_manage(ctx)
    assert install_calls == ["/tmp/demo skill"]
    assert "已安装 skill" in out.content


@pytest.mark.asyncio
async def test_skill_manage_uninstall_calls_manager(monkeypatch) -> None:
    uninstall_calls: list[str] = []

    class _FakeManager:
        def uninstall(self, skill_key: str):
            uninstall_calls.append(skill_key)
            return True, f"已卸载 skill：`{skill_key}`。"

    monkeypatch.setattr(
        "nomi.command.handlers.skills.SkillManager",
        lambda: _FakeManager(),
    )

    ctx = _make_ctx("/skill uninstall demo")
    ctx.args = "uninstall demo"
    out = await cmd_skill_manage(ctx)
    assert uninstall_calls == ["demo"]
    assert "已卸载 skill" in out.content


@pytest.mark.asyncio
async def test_skill_manage_invalid_usage_returns_help() -> None:
    ctx = _make_ctx("/skill invalid")
    ctx.args = "invalid"
    out = await cmd_skill_manage(ctx)
    assert "/skill list" in out.content
    assert "/skill install <source>" in out.content
    assert "/skill uninstall <name>" in out.content


@pytest.mark.asyncio
async def test_bare_skill_command_is_not_registered() -> None:
    router = CommandRouter()
    register_builtin_commands(router)

    ctx = _make_ctx("/skill")
    result = await router.dispatch(ctx)

    assert result is None


@pytest.mark.asyncio
async def test_user_review_command_lists_pending_candidates() -> None:
    class _FakeProfile:
        def render_review_text(self, *, session_key=None):
            assert session_key == "cli:direct"
            return "## 待确认用户画像\n- `user_prof_0001` 沟通偏好.回复风格 -> 直接简洁"

    ctx = _make_ctx("/user-review")
    ctx.loop = SimpleNamespace(user_profile=_FakeProfile())
    from nomi.command.handlers.user_profile import cmd_user_review

    out = await cmd_user_review(ctx)
    assert "待确认用户画像" in out.content
    assert "user_prof_0001" in out.content


@pytest.mark.asyncio
async def test_user_apply_command_calls_service() -> None:
    called: list[str] = []

    class _FakeProfile:
        def apply_candidate(self, candidate_id: str):
            called.append(candidate_id)
            return UserProfileCandidate(
                id=candidate_id,
                status="applied",
                created_at="",
                updated_at="",
                session_key="cli:direct",
                source_text="我喜欢简洁",
                field="沟通偏好.回复风格",
                operation="set",
                value="直接简洁",
            )

    ctx = _make_ctx("/user-apply user_prof_0001")
    ctx.args = "user_prof_0001"
    ctx.loop = SimpleNamespace(user_profile=_FakeProfile())
    from nomi.command.handlers.user_profile import cmd_user_apply

    out = await cmd_user_apply(ctx)
    assert called == ["user_prof_0001"]
    assert "已更新 USER.md" in out.content


@pytest.mark.asyncio
async def test_user_reject_command_calls_service() -> None:
    called: list[str] = []

    class _FakeProfile:
        def reject_candidate(self, candidate_id: str):
            called.append(candidate_id)
            return UserProfileCandidate(
                id=candidate_id,
                status="rejected",
                created_at="",
                updated_at="",
                session_key="cli:direct",
                source_text="我不喜欢太长",
                field="沟通偏好.长短偏好",
                operation="set",
                value="简短直接",
            )

    ctx = _make_ctx("/user-reject user_prof_0001")
    ctx.args = "user_prof_0001"
    ctx.loop = SimpleNamespace(user_profile=_FakeProfile())
    from nomi.command.handlers.user_profile import cmd_user_reject

    out = await cmd_user_reject(ctx)
    assert called == ["user_prof_0001"]
    assert "已忽略该画像候选" in out.content
