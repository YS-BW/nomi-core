"""实例关系文件存储。"""

from __future__ import annotations

import fcntl
import json
from collections.abc import Callable
from pathlib import Path

from nomi.instance_channel.models import (
    InstanceInvite,
    InstanceRelation,
    InstanceRelationRequest,
    normalize_key,
)


class _JsonFileStore:
    """带文件锁保护的 JSON 文件存储。"""

    def __init__(self, path: Path) -> None:
        """绑定存储路径。"""
        self.path = path
        self._lock_path = path.with_suffix(".lock")

    def read(self) -> dict:
        """读取原始 JSON payload。"""
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def write(self, payload: dict) -> None:
        """写回 JSON payload。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def update(self, mutate: Callable[[dict], dict]) -> dict:
        """在文件锁保护下更新 JSON payload。"""
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            payload = mutate(self.read())
            self.write(payload)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            return payload


class InstanceInviteStore:
    """维护当前 instance 的一次性邀请码。"""

    def __init__(self, path: Path) -> None:
        """绑定邀请码文件路径。"""
        self._store = _JsonFileStore(path)

    def get(self) -> InstanceInvite | None:
        """读取当前有效邀请码。"""
        return InstanceInvite.from_dict(self._store.read())

    def put(self, invite: InstanceInvite) -> InstanceInvite:
        """写入当前有效邀请码。"""
        self._store.write(invite.to_dict() | {"version": 1})
        return invite

    def mark_used(self, invite_id: str, used_at_ms: int) -> InstanceInvite:
        """把邀请码标记为已使用。"""
        normalized = str(invite_id or "").strip()
        marked: InstanceInvite | None = None

        def _mutate(payload: dict) -> dict:
            nonlocal marked
            current = InstanceInvite.from_dict(payload)
            if current is None or current.invite_id != normalized:
                raise ValueError("invite code is not current")
            if current.used_at_ms is not None:
                raise ValueError("invite code already used")
            current.used_at_ms = used_at_ms
            marked = current
            return current.to_dict() | {"version": 1}

        self._store.update(_mutate)
        if marked is None:
            raise ValueError("invite code is not current")
        return marked


class InstanceRelationRequestStore:
    """维护当前 instance 的临时关系申请。"""

    def __init__(self, path: Path) -> None:
        """绑定申请文件路径。"""
        self._store = _JsonFileStore(path)

    def list(self) -> list[InstanceRelationRequest]:
        """列出全部 pending 申请。"""
        return [
            InstanceRelationRequest.from_dict(key, item)
            for key, item in sorted(self._read_requests().items())
            if isinstance(item, dict)
        ]

    def get(self, key: str) -> InstanceRelationRequest | None:
        """按 key 读取申请。"""
        normalized = normalize_key(key)
        item = self._read_requests().get(normalized)
        if not isinstance(item, dict):
            return None
        return InstanceRelationRequest.from_dict(normalized, item)

    def put(self, request: InstanceRelationRequest) -> InstanceRelationRequest:
        """写入或覆盖一条 pending 申请。"""
        normalized = normalize_key(request.key)
        request.key = normalized

        def _mutate(payload: dict) -> dict:
            requests = _payload_items(payload, "requests")
            requests[normalized] = request.to_dict()
            return {"version": 1, "requests": requests}

        self._store.update(_mutate)
        return request

    def delete(self, key: str) -> bool:
        """删除一条申请。"""
        normalized = normalize_key(key)
        changed = False

        def _mutate(payload: dict) -> dict:
            nonlocal changed
            requests = _payload_items(payload, "requests")
            changed = normalized in requests
            requests.pop(normalized, None)
            return {"version": 1, "requests": requests}

        self._store.update(_mutate)
        return changed

    def _read_requests(self) -> dict[str, dict]:
        """读取申请字典。"""
        return _payload_items(self._store.read(), "requests")


class InstanceRelationStore:
    """维护当前 instance 的已接受关系。"""

    def __init__(self, path: Path) -> None:
        """绑定关系文件路径。"""
        self._store = _JsonFileStore(path)

    def list(self) -> list[InstanceRelation]:
        """返回全部关系。"""
        relations = []
        for key, item in sorted(self._read_relations().items()):
            if not isinstance(item, dict):
                continue
            relation = InstanceRelation.from_dict(key, item)
            if relation is not None:
                relations.append(relation)
        return relations

    def get(self, key: str) -> InstanceRelation | None:
        """按 key 读取关系。"""
        normalized = normalize_key(key)
        item = self._read_relations().get(normalized)
        return InstanceRelation.from_dict(normalized, item) if isinstance(item, dict) else None

    def find_by_relation_id(self, relation_id: str) -> InstanceRelation | None:
        """按 relation_id 查找关系。"""
        normalized = str(relation_id or "").strip()
        if not normalized:
            return None
        for relation in self.list():
            if relation.relation_id == normalized:
                return relation
        return None

    def put(self, relation: InstanceRelation) -> InstanceRelation:
        """写入或覆盖一条关系。"""
        normalized = normalize_key(relation.key)
        relation.key = normalized

        def _mutate(payload: dict) -> dict:
            relations = _payload_items(payload, "relations")
            relations[normalized] = relation.to_dict()
            return {"version": 1, "relations": relations}

        self._store.update(_mutate)
        return relation

    def delete(self, key: str) -> bool:
        """删除一条关系。"""
        normalized = normalize_key(key)
        changed = False

        def _mutate(payload: dict) -> dict:
            nonlocal changed
            relations = _payload_items(payload, "relations")
            changed = normalized in relations
            relations.pop(normalized, None)
            return {"version": 1, "relations": relations}

        self._store.update(_mutate)
        return changed

    def _read_relations(self) -> dict[str, dict]:
        """读取关系字典。"""
        return _payload_items(self._store.read(), "relations")


def _payload_items(payload: dict, key: str) -> dict[str, dict]:
    """读取 payload 中的命名子字典。"""
    items = payload.get(key)
    return dict(items) if isinstance(items, dict) else {}
