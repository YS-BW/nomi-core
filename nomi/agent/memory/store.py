"""记忆存储与 Dream 历史 owner。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from loguru import logger

from nomi.utils.fs import ensure_dir
from nomi.utils.gitstore import CommitInfo, GitStore
from nomi.utils.text import strip_think


@dataclass(slots=True)
class DreamVersion:
    """表示一条 Dream 历史版本记录。"""

    sha: str
    message: str
    timestamp: str

    @classmethod
    def from_commit(cls, commit: CommitInfo) -> "DreamVersion":
        """把 Git 提交信息转换成 Dream 版本对象。

        参数:
            commit: Git 历史中的提交记录。

        返回:
            对应的 Dream 版本对象。
        """
        return cls(sha=commit.sha, message=commit.message, timestamp=commit.timestamp)


@dataclass(slots=True)
class DreamLogDetails:
    """表示一次 Dream 版本查看结果。"""

    status: str
    requested_sha: str | None = None
    commit: DreamVersion | None = None
    diff: str = ""
    changed_files: list[str] = field(default_factory=list)
    message: str | None = None


@dataclass(slots=True)
class DreamRestoreDetails:
    """表示一次 Dream 版本恢复结果。"""

    status: str
    requested_sha: str
    new_sha: str | None = None
    changed_files: list[str] = field(default_factory=list)
    message: str | None = None


UserProfileStatus = Literal["pending", "applied", "rejected", "superseded"]
UserProfileOperation = Literal["set", "add"]


@dataclass(slots=True)
class UserProfileCandidate:
    """表示一条待确认或已处理的用户画像候选。"""

    id: str
    status: UserProfileStatus
    created_at: str
    updated_at: str
    session_key: str
    source_text: str
    field: str
    operation: UserProfileOperation
    value: str
    old_value: str | None = None
    reason: str = ""
    confidence: float = 0.0
    prompt_count: int = 0
    last_prompted_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserProfileCandidate":
        """从字典恢复用户画像候选。"""
        return cls(
            id=str(data.get("id") or ""),
            status=data.get("status") or "pending",
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            session_key=str(data.get("session_key") or ""),
            source_text=str(data.get("source_text") or ""),
            field=str(data.get("field") or ""),
            operation=(data.get("operation") or "set"),
            value=str(data.get("value") or ""),
            old_value=data.get("old_value"),
            reason=str(data.get("reason") or ""),
            confidence=float(data.get("confidence") or 0.0),
            prompt_count=int(data.get("prompt_count") or 0),
            last_prompted_at=data.get("last_prompted_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        """导出为可持久化字典。"""
        return asdict(self)


class MemoryStore:
    """负责维护记忆目录里的文件事实，不承担模型决策逻辑。"""

    _DEFAULT_MAX_HISTORY = 1000

    def __init__(self, workspace: Path, max_history_entries: int = _DEFAULT_MAX_HISTORY):
        """建立记忆目录下各类文件的固定读写入口。

        参数:
            workspace: 当前工作区目录。
            max_history_entries: history.jsonl 保留的最大条数。

        返回:
            无返回值。
        """
        self.workspace = workspace
        self.max_history_entries = max_history_entries
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "history.jsonl"
        self.user_profile_candidates_file = self.memory_dir / "user_profile_candidates.json"
        self.soul_file = workspace / "SOUL.md"
        self.user_file = workspace / "USER.md"
        self._cursor_file = self.memory_dir / ".cursor"
        self._dream_cursor_file = self.memory_dir / ".dream_cursor"
        self._git = GitStore(
            workspace,
            tracked_files=["SOUL.md", "USER.md", "memory/MEMORY.md"],
        )
        self._cleanup_legacy_history_files()

    @property
    def git(self) -> GitStore:
        """暴露记忆目录对应的 GitStore。

        参数:
            无。

        返回:
            当前记忆目录对应的 GitStore 实例。
        """
        return self._git

    @staticmethod
    def read_file(path: Path) -> str:
        """读取文本文件，并把“文件不存在”统一折叠为空字符串。

        参数:
            path: 待读取的文件路径。

        返回:
            文件文本；缺失时返回空字符串。
        """
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def read_memory(self) -> str:
        """读取长期记忆文件。

        参数:
            无。

        返回:
            `MEMORY.md` 的文本内容；缺失时返回空字符串。
        """
        return self.read_file(self.memory_file)

    def write_memory(self, content: str) -> None:
        """写入长期记忆文件。

        参数:
            content: 需要写入 `MEMORY.md` 的文本。

        返回:
            无返回值。
        """
        self.memory_file.write_text(content, encoding="utf-8")

    def read_soul(self) -> str:
        """读取 `SOUL.md`。

        参数:
            无。

        返回:
            `SOUL.md` 的文本内容；缺失时返回空字符串。
        """
        return self.read_file(self.soul_file)

    def write_soul(self, content: str) -> None:
        """写入 `SOUL.md`。

        参数:
            content: 需要写入的文本内容。

        返回:
            无返回值。
        """
        self.soul_file.write_text(content, encoding="utf-8")

    def read_user(self) -> str:
        """读取 `USER.md`。

        参数:
            无。

        返回:
            `USER.md` 的文本内容；缺失时返回空字符串。
        """
        return self.read_file(self.user_file)

    def write_user(self, content: str) -> None:
        """写入 `USER.md`。

        参数:
            content: 需要写入的文本内容。

        返回:
            无返回值。
        """
        self.user_file.write_text(content, encoding="utf-8")

    def read_user_profile_candidates(self) -> list[UserProfileCandidate]:
        """读取当前用户画像候选列表。"""
        payload = self._read_user_profile_candidates_payload()
        items = payload.get("items") or []
        return [UserProfileCandidate.from_dict(item) for item in items if isinstance(item, dict)]

    def save_user_profile_candidates(self, candidates: list[UserProfileCandidate]) -> None:
        """整体写回用户画像候选列表。"""
        payload = {
            "version": 1,
            "items": [candidate.to_dict() for candidate in candidates],
        }
        self.user_profile_candidates_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def upsert_user_profile_candidate(self, candidate: UserProfileCandidate) -> UserProfileCandidate:
        """按字段和值合并或写入一条画像候选。"""
        candidates = self.read_user_profile_candidates()
        now = self._now_iso()
        for existing in candidates:
            if (
                existing.status == "pending"
                and existing.session_key == candidate.session_key
                and existing.field == candidate.field
                and existing.value == candidate.value
            ):
                existing.source_text = candidate.source_text
                existing.reason = candidate.reason
                existing.confidence = max(existing.confidence, candidate.confidence)
                existing.updated_at = now
                self.save_user_profile_candidates(candidates)
                return existing

        replaced: UserProfileCandidate | None = None
        for existing in candidates:
            if existing.status != "pending" or existing.field != candidate.field:
                continue
            replaced = existing
            break
        if replaced is not None:
            replaced.status = "superseded"
            replaced.updated_at = now
            candidate.old_value = replaced.value if replaced.value else candidate.old_value

        if not candidate.id:
            candidate.id = self._next_user_profile_candidate_id(candidates)
        candidate.status = "pending"
        candidate.created_at = candidate.created_at or now
        candidate.updated_at = now
        candidates.append(candidate)
        self.save_user_profile_candidates(candidates)
        return candidate

    def list_pending_user_profile_candidates(
        self,
        *,
        session_key: str | None = None,
    ) -> list[UserProfileCandidate]:
        """列出待确认的画像候选。"""
        candidates = [
            candidate
            for candidate in self.read_user_profile_candidates()
            if candidate.status == "pending"
        ]
        if session_key is not None:
            candidates = [candidate for candidate in candidates if candidate.session_key == session_key]
        return candidates

    def mark_user_profile_candidates_prompted(self, candidate_ids: list[str]) -> None:
        """更新候选的提醒次数和最近提醒时间。"""
        if not candidate_ids:
            return
        candidates = self.read_user_profile_candidates()
        now = self._now_iso()
        changed = False
        target_ids = set(candidate_ids)
        for candidate in candidates:
            if candidate.id not in target_ids:
                continue
            candidate.prompt_count += 1
            candidate.last_prompted_at = now
            candidate.updated_at = now
            changed = True
        if changed:
            self.save_user_profile_candidates(candidates)

    def reject_user_profile_candidate(self, candidate_id: str) -> UserProfileCandidate | None:
        """拒绝一条待确认画像候选。"""
        candidates = self.read_user_profile_candidates()
        now = self._now_iso()
        for candidate in candidates:
            if candidate.id != candidate_id:
                continue
            candidate.status = "rejected"
            candidate.updated_at = now
            self.save_user_profile_candidates(candidates)
            return candidate
        return None

    def apply_user_profile_candidate(self, candidate_id: str) -> UserProfileCandidate | None:
        """把一条画像候选写入 USER.md 并标记为已应用。"""
        candidates = self.read_user_profile_candidates()
        target: UserProfileCandidate | None = None
        for candidate in candidates:
            if candidate.id == candidate_id:
                target = candidate
                break
        if target is None:
            return None

        profile = self.read_user_profile_document()
        self._apply_user_profile_change(profile, target)
        self.write_user(self.render_user_profile_document(profile))

        now = self._now_iso()
        target.status = "applied"
        target.updated_at = now
        for candidate in candidates:
            if (
                candidate.id != target.id
                and candidate.status == "pending"
                and candidate.field == target.field
            ):
                candidate.status = "superseded"
                candidate.updated_at = now
        self.save_user_profile_candidates(candidates)
        return target

    def read_user_profile_document(self) -> dict[str, Any]:
        """读取当前 USER.md 对应的结构化画像文档。"""
        text = self.read_user()
        defaults = self._default_user_profile_document()
        if not text.strip():
            return defaults

        current_section: str | None = None
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("## "):
                current_section = line[3:].strip()
                continue
            if not line.startswith("- ") or current_section is None:
                continue
            body = line[2:]
            if "：" not in body:
                continue
            label, value = body.split("：", 1)
            self._assign_user_profile_field(defaults, current_section, label.strip(), value.strip())
        return defaults

    def render_user_profile_document(self, profile: dict[str, Any]) -> str:
        """把结构化画像渲染为稳定的 USER.md 文本。"""
        lines = [
            "# 用户画像",
            "",
            "这里记录已经确认的长期用户画像，帮助助手更贴近你地交流。",
            "",
            "## 基本信息",
            f"- 姓名：{profile['基本信息']['姓名'] or '-'}",
            f"- 时区：{profile['基本信息']['时区'] or '-'}",
            f"- 常用语言：{profile['基本信息']['常用语言'] or '-'}",
            "",
            "## 沟通偏好",
            f"- 回复风格：{profile['沟通偏好']['回复风格'] or '-'}",
            f"- 长短偏好：{profile['沟通偏好']['长短偏好'] or '-'}",
            f"- 格式偏好：{profile['沟通偏好']['格式偏好'] or '-'}",
            f"- 回复方式偏好：{profile['沟通偏好']['回复方式偏好'] or '-'}",
            "",
            "## 背景与角色",
            f"- 主要身份：{profile['背景与角色']['主要身份'] or '-'}",
            f"- 技术背景：{profile['背景与角色']['技术背景'] or '-'}",
            f"- 常用工具 / 语言 / 平台：{profile['背景与角色']['常用工具 / 语言 / 平台'] or '-'}",
            "",
            "## 长期兴趣",
        ]
        interests = profile["长期兴趣"]
        if interests:
            lines.extend(f"- {item}" for item in interests)
        else:
            lines.append("- -")
        lines.extend(
            [
                "",
                "## 明确偏好与禁忌",
            ]
        )
        likes = profile["明确偏好与禁忌"]["喜欢什么"]
        dislikes = profile["明确偏好与禁忌"]["不喜欢什么"]
        lines.append(f"- 喜欢什么：{self._join_list_for_markdown(likes)}")
        lines.append(f"- 不喜欢什么：{self._join_list_for_markdown(dislikes)}")
        lines.extend(
            [
                "",
                "---",
                "",
                "*这个文件只保留已经确认的长期用户画像。*",
            ]
        )
        return "\n".join(lines)

    def get_memory_context(self) -> str:
        """返回可直接注入提示词的长期记忆片段。

        参数:
            无。

        返回:
            带标题的长期记忆文本；为空时返回空字符串。
        """
        long_term = self.read_memory()
        return f"## 长期记忆\n{long_term}" if long_term else ""

    def ensure_user_profile_initialized(self) -> None:
        """在 USER.md 为空时写入默认模板。"""
        if self.read_user().strip():
            return
        self.write_user(self.render_user_profile_document(self._default_user_profile_document()))

    def append_history(self, entry: str) -> int:
        """向历史文件追加一条记录。

        参数:
            entry: 需要写入历史的文本内容。

        返回:
            新写入记录对应的自增游标。
        """
        cursor = self._next_cursor()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        record = {
            "cursor": cursor,
            "timestamp": timestamp,
            "content": strip_think(entry.rstrip()) or entry.rstrip(),
        }
        with open(self.history_file, "a", encoding="utf-8") as history_file:
            history_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._cursor_file.write_text(str(cursor), encoding="utf-8")
        return cursor

    def _next_cursor(self) -> int:
        """读取当前游标并返回下一值。"""
        if self._cursor_file.exists():
            try:
                return int(self._cursor_file.read_text(encoding="utf-8").strip()) + 1
            except (ValueError, OSError):
                pass
        # 游标文件损坏时退回到读取 JSONL 最后一行，避免历史追加中断。
        last_entry = self._read_last_entry()
        if last_entry:
            return last_entry["cursor"] + 1
        return 1

    def _cleanup_legacy_history_files(self) -> None:
        """清理已废弃的 HISTORY.md 及其备份文件。"""
        for path in self.memory_dir.glob("HISTORY.md*"):
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                logger.debug("Skip removing legacy history file {}: {}", path, exc)

    def read_unprocessed_history(self, since_cursor: int) -> list[dict[str, Any]]:
        """读取指定游标之后尚未处理的历史记录。

        参数:
            since_cursor: 已处理到的最后游标。

        返回:
            游标大于该值的历史记录列表。
        """
        return [entry for entry in self._read_entries() if entry["cursor"] > since_cursor]

    def compact_history(self) -> None:
        """在历史条目超限时裁掉最旧记录。

        参数:
            无。

        返回:
            无返回值。
        """
        if self.max_history_entries <= 0:
            return
        entries = self._read_entries()
        if len(entries) <= self.max_history_entries:
            return
        kept = entries[-self.max_history_entries :]
        self._write_entries(kept)

    def _read_entries(self) -> list[dict[str, Any]]:
        """读取 history.jsonl 全部记录。"""
        entries: list[dict[str, Any]] = []
        try:
            with open(self.history_file, "r", encoding="utf-8") as history_file:
                for line in history_file:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass
        return entries

    def _read_last_entry(self) -> dict[str, Any] | None:
        """高效读取 JSONL 最后一条记录。"""
        try:
            with open(self.history_file, "rb") as history_file:
                history_file.seek(0, 2)
                size = history_file.tell()
                if size == 0:
                    return None
                read_size = min(size, 4096)
                history_file.seek(size - read_size)
                data = history_file.read().decode("utf-8")
                lines = [line for line in data.split("\n") if line.strip()]
                if not lines:
                    return None
                return json.loads(lines[-1])
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _write_entries(self, entries: list[dict[str, Any]]) -> None:
        """用给定记录整体覆盖 history.jsonl。"""
        with open(self.history_file, "w", encoding="utf-8") as history_file:
            for entry in entries:
                history_file.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_last_dream_cursor(self) -> int:
        """读取 Dream 已处理到的最后游标。

        参数:
            无。

        返回:
            已处理到的游标值；缺失时返回 0。
        """
        if self._dream_cursor_file.exists():
            try:
                return int(self._dream_cursor_file.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                pass
        return 0

    def set_last_dream_cursor(self, cursor: int) -> None:
        """写入 Dream 已处理到的最后游标。

        参数:
            cursor: 需要保存的最新游标值。

        返回:
            无返回值。
        """
        self._dream_cursor_file.write_text(str(cursor), encoding="utf-8")

    def list_dream_versions(self, max_entries: int = 10) -> list[DreamVersion]:
        """列出最近的 Dream 历史版本。

        参数:
            max_entries: 最多返回多少条版本记录。

        返回:
            版本列表；未初始化时返回空列表。
        """
        if not self.git.is_initialized():
            return []
        return [DreamVersion.from_commit(commit) for commit in self.git.log(max_entries=max_entries)]

    def show_dream_version(self, sha: str | None = None) -> DreamLogDetails:
        """查看最近一次或指定 Dream 版本差异。

        参数:
            sha: 可选的目标提交 SHA。

        返回:
            Dream 版本查看结果对象。
        """
        if not self.git.is_initialized():
            if self.get_last_dream_cursor() == 0:
                return DreamLogDetails(status="never_run", requested_sha=sha)
            return DreamLogDetails(status="unavailable", requested_sha=sha)

        target_sha = sha
        if target_sha is None:
            commits = self.git.log(max_entries=1)
            if not commits:
                return DreamLogDetails(status="empty")
            target_sha = commits[0].sha

        result = self.git.show_commit_diff(target_sha)
        if result is None:
            return DreamLogDetails(status="not_found", requested_sha=target_sha)

        commit, diff = result
        return DreamLogDetails(
            status="ok",
            requested_sha=sha,
            commit=DreamVersion.from_commit(commit),
            diff=diff,
            changed_files=self._extract_changed_files(diff),
        )

    def restore_dream_version(self, sha: str) -> DreamRestoreDetails:
        """把 Dream 记忆恢复到指定版本之前的状态。

        参数:
            sha: 需要回退的 Dream 提交 SHA。

        返回:
            Dream 恢复结果对象。
        """
        if not self.git.is_initialized():
            return DreamRestoreDetails(status="unavailable", requested_sha=sha)

        result = self.git.show_commit_diff(sha)
        changed_files = self._extract_changed_files(result[1]) if result else []
        new_sha = self.git.revert(sha)
        if new_sha is None:
            return DreamRestoreDetails(
                status="not_found",
                requested_sha=sha,
                changed_files=changed_files,
            )
        return DreamRestoreDetails(
            status="ok",
            requested_sha=sha,
            new_sha=new_sha,
            changed_files=changed_files,
        )

    @staticmethod
    def _extract_changed_files(diff: str) -> list[str]:
        """从 unified diff 中提取变更文件路径。"""
        files: list[str] = []
        seen: set[str] = set()
        for line in diff.splitlines():
            if not line.startswith("diff --git "):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            path = parts[3]
            if path.startswith("b/"):
                path = path[2:]
            if path in seen:
                continue
            seen.add(path)
            files.append(path)
        return files

    @staticmethod
    def _format_messages(messages: list[dict]) -> str:
        """把消息数组格式化成归档文本。"""
        lines: list[str] = []
        for message in messages:
            if not message.get("content"):
                continue
            tools = (
                f" [tools: {', '.join(message['tools_used'])}]"
                if message.get("tools_used")
                else ""
            )
            lines.append(
                f"[{message.get('timestamp', '?')[:16]}] "
                f"{message['role'].upper()}{tools}: {message['content']}"
            )
        return "\n".join(lines)

    def raw_archive(self, messages: list[dict]) -> None:
        """在摘要失败时把原始消息直接写入历史归档。

        参数:
            messages: 需要兜底归档的消息数组。

        返回:
            无返回值。
        """
        self.append_history(
            f"[RAW] {len(messages)} messages\n"
            f"{self._format_messages(messages)}"
        )
        logger.warning(
            "Memory consolidation degraded: raw-archived {} messages",
            len(messages),
        )

    def _read_user_profile_candidates_payload(self) -> dict[str, Any]:
        """读取用户画像候选状态文件。"""
        if not self.user_profile_candidates_file.exists():
            return {"version": 1, "items": []}
        try:
            payload = json.loads(self.user_profile_candidates_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "items": []}
        if not isinstance(payload, dict):
            return {"version": 1, "items": []}
        items = payload.get("items")
        if not isinstance(items, list):
            payload["items"] = []
        payload.setdefault("version", 1)
        return payload

    @staticmethod
    def _now_iso() -> str:
        """返回当前 ISO 时间字符串。"""
        return datetime.now().isoformat()

    @staticmethod
    def _default_user_profile_document() -> dict[str, Any]:
        """返回默认用户画像结构。"""
        return {
            "基本信息": {
                "姓名": "",
                "时区": "",
                "常用语言": "",
            },
            "沟通偏好": {
                "回复风格": "",
                "长短偏好": "",
                "格式偏好": "",
                "回复方式偏好": "",
            },
            "背景与角色": {
                "主要身份": "",
                "技术背景": "",
                "常用工具 / 语言 / 平台": "",
            },
            "长期兴趣": [],
            "明确偏好与禁忌": {
                "喜欢什么": [],
                "不喜欢什么": [],
            },
        }

    @staticmethod
    def _join_list_for_markdown(items: list[str]) -> str:
        """把列表字段渲染成单行 Markdown 文本。"""
        cleaned = [item.strip() for item in items if item.strip()]
        return "、".join(cleaned) if cleaned else "-"

    @classmethod
    def _assign_user_profile_field(
        cls,
        profile: dict[str, Any],
        section: str,
        label: str,
        value: str,
    ) -> None:
        """把 USER.md 中的一行值写回结构化画像。"""
        clean_value = value.strip()
        if section == "长期兴趣":
            if clean_value and clean_value != "-":
                profile["长期兴趣"].append(clean_value)
            return

        target = profile.get(section)
        if not isinstance(target, dict) or label not in target:
            return

        if isinstance(target[label], list):
            target[label] = cls._split_markdown_list(clean_value)
            return
        target[label] = "" if clean_value == "-" else clean_value

    @staticmethod
    def _split_markdown_list(value: str) -> list[str]:
        """把单行列表文本拆回列表。"""
        if not value or value == "-":
            return []
        parts: list[str] = []
        for item in value.replace("，", "、").split("、"):
            clean = item.strip()
            if clean:
                parts.append(clean)
        return parts

    @staticmethod
    def _field_path_to_location(field_path: str) -> tuple[str, str | None]:
        """把业务字段路径映射到结构化画像位置。"""
        parts = [part.strip() for part in field_path.split(".") if part.strip()]
        if not parts:
            return ("", None)
        if len(parts) == 1:
            return (parts[0], None)
        return (parts[0], parts[1])

    def _apply_user_profile_change(
        self,
        profile: dict[str, Any],
        candidate: UserProfileCandidate,
    ) -> None:
        """把候选变更应用到结构化画像。"""
        section, label = self._field_path_to_location(candidate.field)
        if not section:
            return

        if section == "长期兴趣":
            items = profile["长期兴趣"]
            if candidate.operation == "add":
                if candidate.value not in items:
                    items.append(candidate.value)
            else:
                profile["长期兴趣"] = [candidate.value]
            return

        if section == "明确偏好与禁忌" and label in {"喜欢什么", "不喜欢什么"}:
            items = profile[section][label]
            if candidate.operation == "add":
                if candidate.value not in items:
                    items.append(candidate.value)
            else:
                profile[section][label] = [candidate.value]
            return

        if label is None:
            return
        section_data = profile.get(section)
        if not isinstance(section_data, dict) or label not in section_data:
            return
        if isinstance(section_data[label], list):
            if candidate.value not in section_data[label]:
                section_data[label].append(candidate.value)
            return
        section_data[label] = candidate.value

    @staticmethod
    def _next_user_profile_candidate_id(
        candidates: list[UserProfileCandidate],
    ) -> str:
        """生成新的画像候选 ID。"""
        max_index = 0
        for candidate in candidates:
            if not candidate.id.startswith("user_prof_"):
                continue
            try:
                max_index = max(max_index, int(candidate.id.rsplit("_", 1)[-1]))
            except ValueError:
                continue
        return f"user_prof_{max_index + 1:04d}"
