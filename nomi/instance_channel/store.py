"""实例关系文件存储。"""

from __future__ import annotations

import fcntl
import json
from pathlib import Path

from nomi.instance_channel.models import InstanceRelation


class InstanceRelationStore:
    """维护当前 instance 的关系表。"""

    def __init__(self, path: Path) -> None:
        """绑定关系文件路径。"""
        self.path = path
        self._lock_path = path.with_suffix(".lock")

    def list(self) -> list[InstanceRelation]:
        """返回全部关系。"""
        return [
            InstanceRelation.from_dict(key, item)
            for key, item in sorted(self._read_relations().items())
            if isinstance(item, dict)
        ]

    def get(self, key: str) -> InstanceRelation | None:
        """按 key 读取关系。"""
        normalized = _normalize_key(key)
        item = self._read_relations().get(normalized)
        return InstanceRelation.from_dict(normalized, item) if isinstance(item, dict) else None

    def find_by_endpoint(self, url: str, token: str) -> InstanceRelation | None:
        """按对端 URL 和 token 查找关系。"""
        normalized_url = str(url or "").strip().rstrip("/")
        normalized_token = str(token or "").strip()
        if not normalized_url or not normalized_token:
            return None
        for relation in self.list():
            if relation.url == normalized_url and relation.token == normalized_token:
                return relation
        return None

    def put(self, relation: InstanceRelation) -> InstanceRelation:
        """写入或覆盖一条关系。"""
        normalized = _normalize_key(relation.key)
        relation.key = normalized

        def _mutate(relations: dict[str, dict]) -> dict[str, dict]:
            relations[normalized] = relation.to_dict()
            return relations

        self._update(_mutate)
        return relation

    def delete(self, key: str) -> bool:
        """删除一条关系。"""
        normalized = _normalize_key(key)
        changed = False

        def _mutate(relations: dict[str, dict]) -> dict[str, dict]:
            nonlocal changed
            changed = normalized in relations
            relations.pop(normalized, None)
            return relations

        self._update(_mutate)
        return changed

    def _read_payload(self) -> dict:
        """读取原始 payload。"""
        if not self.path.exists():
            return {"version": 1, "relations": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"version": 1, "relations": {}}
        return payload if isinstance(payload, dict) else {"version": 1, "relations": {}}

    def _read_relations(self) -> dict[str, dict]:
        """读取关系字典。"""
        payload = self._read_payload()
        relations = payload.get("relations")
        return relations if isinstance(relations, dict) else {}

    def _write_relations(self, relations: dict[str, dict]) -> None:
        """写回关系字典。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "relations": relations}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _update(self, mutate) -> None:
        """在文件锁保护下更新关系表。"""
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            relations = self._read_relations()
            self._write_relations(mutate(relations))
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _normalize_key(key: str) -> str:
    """规范化关系 key。"""
    normalized = str(key or "").strip().lower()
    if not normalized:
        raise ValueError("instance relation key cannot be empty")
    if ":" in normalized or "/" in normalized:
        raise ValueError("instance relation key cannot contain ':' or '/'")
    return normalized
