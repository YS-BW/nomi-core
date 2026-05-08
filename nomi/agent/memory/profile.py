"""用户画像候选抽取、确认与提醒服务。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from loguru import logger

from nomi.agent.memory.store import MemoryStore, UserProfileCandidate
from nomi.providers.base import LLMProvider

_PROFILE_EXTRACTION_SYSTEM_PROMPT = """你负责从一轮对话里抽取“长期用户画像候选”。

只输出 JSON，对应格式：
{"items":[{"field":"沟通偏好.回复风格","operation":"set","value":"直接简洁","reason":"...","source_text":"...","confidence":0.92,"stable":true}]}

严格规则：
1. 只抽取用户明确表达的长期画像，不要推断。
2. 只保留稳定偏好、长期背景、长期兴趣、明确禁忌。
3. 以下内容一律丢弃：临时安排、一次性提醒、短期任务、当天情绪、当前项目短期上下文。
4. field 只能使用这些路径：
   - 基本信息.姓名
   - 基本信息.时区
   - 基本信息.常用语言
   - 沟通偏好.回复风格
   - 沟通偏好.长短偏好
   - 沟通偏好.格式偏好
   - 沟通偏好.回复方式偏好
   - 背景与角色.主要身份
   - 背景与角色.技术背景
   - 背景与角色.常用工具 / 语言 / 平台
   - 长期兴趣
   - 明确偏好与禁忌.喜欢什么
   - 明确偏好与禁忌.不喜欢什么
5. operation 只能是 set 或 add。
6. 如果没有候选，返回 {"items":[]}。
7. 不要输出 markdown，不要输出解释文字，不要包裹代码块。
"""

_FAST_CONFIRM_WORDS = {"记住", "更新", "可以记", "是的记下", "记下", "好，记住", "好的记住"}
_FAST_REJECT_WORDS = {"不要记", "不用记", "忽略", "别记", "先别记"}
_REMINDER_COOLDOWN = timedelta(minutes=30)
_PROFILE_SIGNAL_MARKERS = (
    "我喜欢",
    "我不喜欢",
    "我更喜欢",
    "我习惯",
    "我通常",
    "我一般",
    "我常用",
    "我用",
    "我希望",
    "我更希望",
    "我叫",
    "我是",
    "我的专业",
    "我的工作",
    "我的角色",
    "我偏好",
    "以后你",
    "你直接一点",
    "你详细一点",
    "请用中文",
    "请说中文",
)


@dataclass(slots=True)
class UserProfileReminder:
    """描述一轮对话后要附带的提醒。"""

    text: str
    candidate_ids: list[str]


@dataclass(slots=True)
class UserProfileQuickAction:
    """描述用户用自然语言触发的快捷确认动作。"""

    action: str
    candidate: UserProfileCandidate


class UserProfileService:
    """负责用户画像候选的抽取、提醒与确认流程。"""

    def __init__(
        self,
        *,
        store: MemoryStore,
        provider: LLMProvider,
        model: str,
    ) -> None:
        """绑定用户画像服务依赖。

        参数:
            store: 画像和候选的文件存储入口。
            provider: 当前主模型 provider。
            model: 当前默认模型名。

        返回:
            无返回值。
        """
        self.store = store
        self.provider = provider
        self.model = model

    async def extract_candidates(
        self,
        *,
        session_key: str,
        user_text: str,
        assistant_text: str,
        recent_history: list[dict[str, Any]] | None = None,
    ) -> list[UserProfileCandidate]:
        """从当前轮次抽取用户画像候选。"""
        if not user_text.strip():
            return []
        user_profile = self.store.read_user() or "(empty)"
        history_excerpt = self._format_recent_history(recent_history or [])
        prompt = (
            f"## 当前 USER.md\n{user_profile}\n\n"
            f"## 最近上下文\n{history_excerpt}\n\n"
            f"## 本轮用户消息\n{user_text}\n\n"
            f"## 本轮助手回复\n{assistant_text}"
        )
        try:
            response = await self.provider.chat_with_retry(
                model=self.model,
                messages=[
                    {"role": "system", "content": _PROFILE_EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                tools=None,
                tool_choice=None,
                max_tokens=800,
                temperature=0,
            )
            parsed = self._parse_extraction_response(response.content or "")
        except Exception:
            logger.exception("User profile candidate extraction failed")
            return []

        out: list[UserProfileCandidate] = []
        for item in parsed:
            if not item.get("stable", True):
                continue
            field = str(item.get("field") or "").strip()
            value = str(item.get("value") or "").strip()
            if not field or not value:
                continue
            candidate = UserProfileCandidate(
                id="",
                status="pending",
                created_at="",
                updated_at="",
                session_key=session_key,
                source_text=str(item.get("source_text") or user_text).strip(),
                field=field,
                operation="add" if item.get("operation") == "add" else "set",
                value=value,
                old_value=self._current_field_value(field),
                reason=str(item.get("reason") or "").strip(),
                confidence=float(item.get("confidence") or 0.0),
                prompt_count=0,
                last_prompted_at=None,
            )
            out.append(self.store.upsert_user_profile_candidate(candidate))
        return out

    def build_reminder(
        self,
        *,
        session_key: str,
        new_candidates: list[UserProfileCandidate],
    ) -> UserProfileReminder | None:
        """为本轮新候选生成提醒文本。"""
        visible = [candidate for candidate in new_candidates if self._should_prompt(candidate)]
        if not visible:
            return None
        lead = visible[0]
        preview = f"{lead.field} = {lead.value}"
        if len(visible) == 1:
            text = (
                f"我注意到一个可能值得记住的画像：{preview}。"
                "要不要记到 USER.md？回复“记住”即可，或用 /user-review 查看。"
            )
        else:
            text = (
                f"我注意到 {len(visible)} 个可能值得记住的画像，其中一个是：{preview}。"
                "要不要记到 USER.md？回复“记住”即可，或用 /user-review 查看。"
            )
        candidate_ids = [candidate.id for candidate in visible]
        self.store.mark_user_profile_candidates_prompted(candidate_ids)
        return UserProfileReminder(text=text, candidate_ids=candidate_ids)

    def should_attempt_extraction(
        self,
        *,
        user_text: str,
        assistant_text: str,
        stop_reason: str,
    ) -> bool:
        """判断当前轮次是否值得发起画像抽取。"""
        if stop_reason != "completed":
            return False
        if not user_text.strip() or not assistant_text.strip():
            return False
        compact = "".join(user_text.strip().split()).lower()
        if len(compact) < 2:
            return False
        return any(marker.lower() in compact for marker in _PROFILE_SIGNAL_MARKERS)

    def detect_quick_action(
        self,
        *,
        session_key: str,
        text: str,
    ) -> UserProfileQuickAction | None:
        """识别是否命中自然语言快捷确认。"""
        normalized = self._normalize_quick_text(text)
        if not normalized:
            return None
        pending = self.store.list_pending_user_profile_candidates(session_key=session_key)
        if not pending:
            return None
        if normalized in _FAST_CONFIRM_WORDS:
            return UserProfileQuickAction(action="apply", candidate=pending[0])
        if normalized in _FAST_REJECT_WORDS:
            return UserProfileQuickAction(action="reject", candidate=pending[0])
        return None

    def apply_candidate(self, candidate_id: str) -> UserProfileCandidate | None:
        """确认并应用一条画像候选。"""
        return self.store.apply_user_profile_candidate(candidate_id)

    def reject_candidate(self, candidate_id: str) -> UserProfileCandidate | None:
        """拒绝一条画像候选。"""
        return self.store.reject_user_profile_candidate(candidate_id)

    def list_pending_candidates(self, *, session_key: str | None = None) -> list[UserProfileCandidate]:
        """列出待确认候选。"""
        return self.store.list_pending_user_profile_candidates(session_key=session_key)

    def render_review_text(self, *, session_key: str | None = None) -> str:
        """渲染待确认候选列表。"""
        candidates = self.list_pending_candidates(session_key=session_key)
        if not candidates:
            return "当前没有待确认的用户画像候选。"
        lines = ["## 待确认用户画像"]
        for candidate in candidates:
            lines.append(
                f"- `{candidate.id}` {candidate.field} -> {candidate.value}"
                f"（来源：{candidate.source_text}）"
            )
        lines.append("")
        lines.append("可执行：`/user-apply <id>` 或 `/user-reject <id>`")
        return "\n".join(lines)

    def render_user_document(self) -> str:
        """返回当前 USER.md 内容。"""
        self.store.ensure_user_profile_initialized()
        return self.store.read_user()

    @staticmethod
    def _normalize_quick_text(text: str) -> str:
        """归一化快捷确认文本。"""
        return "".join(text.strip().split())

    @staticmethod
    def _parse_extraction_response(content: str) -> list[dict[str, Any]]:
        """解析模型返回的 JSON 候选列表。"""
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if "\n" in text:
                text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3].strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("User profile extraction returned invalid JSON: {}", content[:300])
            return []
        items = payload.get("items") if isinstance(payload, dict) else None
        return items if isinstance(items, list) else []

    @staticmethod
    def _format_recent_history(history: list[dict[str, Any]]) -> str:
        """把最近历史压成短文本。"""
        if not history:
            return "(empty)"
        lines: list[str] = []
        for message in history[-6:]:
            role = str(message.get("role") or "?")
            content = message.get("content")
            if not isinstance(content, str):
                continue
            compact = content.strip().replace("\n", " ")
            if not compact:
                continue
            lines.append(f"{role}: {compact[:160]}")
        return "\n".join(lines) if lines else "(empty)"

    def _current_field_value(self, field: str) -> str | None:
        """读取当前 USER.md 中对应字段的已有值。"""
        profile = self.store.read_user_profile_document()
        section, label = self.store._field_path_to_location(field)
        if not section:
            return None
        if section == "长期兴趣":
            items = profile["长期兴趣"]
            return "、".join(items) if items else None
        if section == "明确偏好与禁忌" and label in {"喜欢什么", "不喜欢什么"}:
            items = profile[section][label]
            return "、".join(items) if items else None
        if label is None:
            return None
        section_data = profile.get(section)
        if not isinstance(section_data, dict):
            return None
        value = section_data.get(label)
        if isinstance(value, list):
            return "、".join(value) if value else None
        return value or None

    @staticmethod
    def _should_prompt(candidate: UserProfileCandidate) -> bool:
        """判断当前候选是否应该再次提醒。"""
        if candidate.status != "pending":
            return False
        if not candidate.last_prompted_at:
            return True
        try:
            last_prompted = datetime.fromisoformat(candidate.last_prompted_at)
        except ValueError:
            return True
        return datetime.now() - last_prompted >= _REMINDER_COOLDOWN
