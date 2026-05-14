"""实例关系模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

RelationPermission = Literal["chat", "task", "all"]
RequestDirection = Literal["incoming", "outgoing"]
RequestStatus = Literal["pending"]

VALID_RELATION_PERMISSIONS: tuple[str, ...] = ("chat", "task", "all")
VALID_REQUEST_DIRECTIONS: tuple[str, ...] = ("incoming", "outgoing")
PERMISSION_LEVELS: dict[str, int] = {"chat": 1, "task": 2, "all": 3}


@dataclass(slots=True)
class InstanceInvite:
    """描述当前唯一有效的一次性邀请码。"""

    invite_id: str
    secret_hash: str
    url: str
    key: str
    created_at_ms: int
    used_at_ms: int | None = None

    @classmethod
    def from_dict(cls, payload: dict) -> "InstanceInvite | None":
        """从持久化字典恢复邀请码。"""
        invite_id = str(payload.get("invite_id") or "").strip()
        secret_hash = str(payload.get("secret_hash") or "").strip()
        url = str(payload.get("url") or "").strip().rstrip("/")
        raw_key = str(payload.get("key") or "").strip()
        if not invite_id or not secret_hash or not url or not raw_key:
            return None
        key = normalize_key(raw_key)
        used_at = payload.get("used_at_ms")
        return cls(
            invite_id=invite_id,
            secret_hash=secret_hash,
            url=url,
            key=key,
            created_at_ms=int(payload.get("created_at_ms") or 0),
            used_at_ms=int(used_at) if used_at else None,
        )

    def to_dict(self) -> dict:
        """导出持久化字典。"""
        return asdict(self)


@dataclass(slots=True)
class InstanceRelationRequest:
    """描述一条临时好友申请。"""

    key: str
    direction: RequestDirection
    url: str
    requested_permission: RelationPermission
    response_token: str
    invite_id: str
    created_at_ms: int

    @classmethod
    def from_dict(cls, key: str, payload: dict) -> "InstanceRelationRequest":
        """从持久化字典恢复好友申请。"""
        direction = str(payload.get("direction") or "incoming").strip()
        permission = str(payload.get("requested_permission") or "chat").strip()
        if direction not in VALID_REQUEST_DIRECTIONS:
            direction = "incoming"
        if permission not in VALID_RELATION_PERMISSIONS:
            permission = "chat"
        return cls(
            key=normalize_key(key),
            direction=direction,  # type: ignore[arg-type]
            url=str(payload.get("url") or "").strip().rstrip("/"),
            requested_permission=permission,  # type: ignore[arg-type]
            response_token=str(payload.get("response_token") or "").strip(),
            invite_id=str(payload.get("invite_id") or "").strip(),
            created_at_ms=int(payload.get("created_at_ms") or 0),
        )

    def to_dict(self) -> dict:
        """导出持久化字典。"""
        payload = asdict(self)
        payload.pop("key", None)
        return payload


@dataclass(slots=True)
class InstanceRelation:
    """描述一条已接受的外部 instance 关系。"""

    key: str
    name: str
    url: str
    relation_id: str
    relation_token: str
    permission: RelationPermission
    created_at_ms: int
    updated_at_ms: int

    @classmethod
    def from_dict(cls, key: str, payload: dict) -> "InstanceRelation | None":
        """从持久化字典恢复关系对象。"""
        relation_id = str(payload.get("relation_id") or "").strip()
        relation_token = str(payload.get("relation_token") or "").strip()
        url = str(payload.get("url") or "").strip().rstrip("/")
        permission = normalize_permission(payload.get("permission") or "chat")
        if not relation_id or not relation_token or not url:
            return None
        return cls(
            key=normalize_key(key),
            name=str(payload.get("name") or "").strip(),
            url=url,
            relation_id=relation_id,
            relation_token=relation_token,
            permission=permission,
            created_at_ms=int(payload.get("created_at_ms") or 0),
            updated_at_ms=int(payload.get("updated_at_ms") or 0),
        )

    def to_dict(self) -> dict:
        """导出持久化字典。"""
        payload = asdict(self)
        payload.pop("key", None)
        return payload

    def allows(self, required: str) -> bool:
        """判断当前关系是否具备指定能力。"""
        return permission_allows(self.permission, required)


def normalize_key(value: object) -> str:
    """规范化 Nomi 对外名字。"""
    key = str(value or "").strip()
    if not key:
        raise ValueError("instance key cannot be empty")
    if ":" in key or "/" in key:
        raise ValueError("instance key cannot contain ':' or '/'")
    if len(key) > 64:
        raise ValueError("instance key must be at most 64 characters")
    return key


def normalize_permission(value: object) -> RelationPermission:
    """校验并规范化权限值。"""
    permission = str(value or "chat").strip().lower()
    if permission not in VALID_RELATION_PERMISSIONS:
        raise ValueError("permission must be one of: chat, task, all")
    return permission  # type: ignore[return-value]


def permission_allows(current: str, required: str) -> bool:
    """判断权限等级是否满足要求。"""
    return PERMISSION_LEVELS.get(current, 0) >= PERMISSION_LEVELS.get(required, 0)
