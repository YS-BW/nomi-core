"""实例关系模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

RelationStatus = Literal["pending", "friend", "trusted"]
RelationPermission = Literal["chat", "task", "all"]

VALID_RELATION_STATUSES: tuple[str, ...] = ("pending", "friend", "trusted")
VALID_RELATION_PERMISSIONS: tuple[str, ...] = ("chat", "task", "all")
PERMISSION_LEVELS: dict[str, int] = {"chat": 1, "task": 2, "all": 3}


@dataclass(slots=True)
class InstanceRelation:
    """描述一个已登记的外部 instance 关系。"""

    key: str
    name: str
    url: str
    token: str
    status: RelationStatus
    permission: RelationPermission
    updated_at_ms: int

    @classmethod
    def from_dict(cls, key: str, payload: dict) -> "InstanceRelation":
        """从持久化字典恢复关系对象。"""
        status = str(payload.get("status") or "pending").strip()
        permission = str(payload.get("permission") or "chat").strip()
        if status not in VALID_RELATION_STATUSES:
            status = "pending"
        if permission not in VALID_RELATION_PERMISSIONS:
            permission = "chat"
        return cls(
            key=str(key or "").strip(),
            name=str(payload.get("name") or "").strip(),
            url=str(payload.get("url") or "").strip().rstrip("/"),
            token=str(payload.get("token") or "").strip(),
            status=status,  # type: ignore[arg-type]
            permission=permission,  # type: ignore[arg-type]
            updated_at_ms=int(payload.get("updated_at_ms") or 0),
        )

    def to_dict(self) -> dict:
        """导出持久化字典。"""
        payload = asdict(self)
        payload.pop("key", None)
        return payload

    def allows(self, required: str) -> bool:
        """判断当前关系是否具备指定能力。"""
        return (
            self.status in {"friend", "trusted"}
            and PERMISSION_LEVELS.get(self.permission, 0) >= PERMISSION_LEVELS.get(required, 0)
        )
