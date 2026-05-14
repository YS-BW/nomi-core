"""实例关系管理器。"""

from __future__ import annotations

import time

from nomi.config.paths import get_instance_relations_path
from nomi.instance_channel.client import InstanceChannelClient
from nomi.instance_channel.models import (
    PERMISSION_LEVELS,
    VALID_RELATION_PERMISSIONS,
    InstanceRelation,
    RelationPermission,
)
from nomi.instance_channel.notification import NotificationService
from nomi.instance_channel.store import InstanceRelationStore


class InstanceRelationManager:
    """管理当前 instance 与其它 instance 的关系。"""

    def __init__(
        self,
        *,
        store: InstanceRelationStore | None = None,
        notification: NotificationService | None = None,
        client: InstanceChannelClient | None = None,
    ) -> None:
        """装配关系存储、通知和网络 client。"""
        self.store = store or InstanceRelationStore(get_instance_relations_path())
        self.notification = notification
        self.client = client or InstanceChannelClient()

    def list_relations(self) -> list[InstanceRelation]:
        """列出全部关系。"""
        return self.store.list()

    def get_relation(self, key: str) -> InstanceRelation | None:
        """读取单个关系。"""
        return self.store.get(key)

    def find_relation_by_endpoint(self, url: str, token: str) -> InstanceRelation | None:
        """按对端 URL 和 token 查找关系。"""
        return self.store.find_by_endpoint(url, token)

    def upsert_pending(self, *, key: str, url: str, token: str, name: str = "") -> InstanceRelation:
        """写入一条 pending 关系。"""
        normalized_url = str(url or "").strip().rstrip("/")
        normalized_token = str(token or "").strip()
        if not normalized_url or not normalized_token:
            raise ValueError("instance relation requires url and token")
        current = self.store.get(key)
        if current:
            if current.url != normalized_url or current.token != normalized_token:
                raise ValueError(f"instance relation conflict: {key}")
            if name:
                current.name = str(name).strip()
            current.updated_at_ms = _now_ms()
            # 已建立关系再次收到相同申请时不能降级为 pending。
            return self.store.put(current)
        relation = InstanceRelation(
            key=key,
            name=name,
            url=normalized_url,
            token=normalized_token,
            status="pending",
            permission="chat",
            updated_at_ms=_now_ms(),
        )
        return self.store.put(relation)

    def accept(self, key: str, permission: str = "chat") -> InstanceRelation:
        """接受一条关系请求。"""
        relation = self._require(key)
        normalized_permission = self.normalize_permission(permission)
        relation.status = "trusted" if normalized_permission == "all" else "friend"
        relation.permission = normalized_permission
        relation.updated_at_ms = _now_ms()
        return self.store.put(relation)

    def reject(self, key: str) -> bool:
        """拒绝并删除一条关系。"""
        return self.store.delete(key)

    def rename(self, key: str, name: str) -> InstanceRelation:
        """更新关系备注名。"""
        relation = self._require(key)
        relation.name = str(name or "").strip()
        relation.updated_at_ms = _now_ms()
        return self.store.put(relation)

    def require_permission(self, key: str, required: str = "chat") -> InstanceRelation:
        """读取关系并校验权限。"""
        relation = self._require(key)
        if not relation.allows(required):
            raise PermissionError(f"instance relation {key} does not allow {required}")
        return relation

    async def send_invite(
        self,
        *,
        key: str,
        url: str,
        token: str,
        payload: dict,
        name: str = "",
    ) -> dict:
        """保存 pending 关系并发起好友申请。"""
        relation = self.upsert_pending(key=key, url=url, token=token, name=name)
        return await self.client.send_relation_request(relation, payload)

    async def notify_relation_request(self, key: str) -> None:
        """通知用户确认关系请求。"""
        if self.notification is None:
            return
        self.notification.enqueue_global(
            notification_id=f"instance_relation_request:{key}",
            content=(
                f"{key} 想添加你为好友。可以回复：同意添加 {key} / 拒绝 {key} / 信任 {key}"
            ),
        )

    async def notify_relation_accepted(self, key: str) -> None:
        """通知用户关系已通过并提示备注。"""
        if self.notification is None:
            return
        self.notification.enqueue_global(
            notification_id=f"instance_relation_accepted:{key}",
            content=f"已添加 {key}。请给这个 instance 取一个备注名，例如：备注 {key} 为 小美",
        )

    @staticmethod
    def normalize_permission(permission: str) -> RelationPermission:
        """校验并规范化权限值。"""
        normalized = str(permission or "chat").strip().lower()
        if normalized not in VALID_RELATION_PERMISSIONS:
            raise ValueError("permission must be one of: chat, task, all")
        return normalized  # type: ignore[return-value]

    def _require(self, key: str) -> InstanceRelation:
        """读取必需关系。"""
        relation = self.store.get(key)
        if relation is None:
            raise ValueError(f"instance relation not found: {key}")
        return relation


def permission_allows(current: str, required: str) -> bool:
    """判断权限等级是否满足要求。"""
    return PERMISSION_LEVELS.get(current, 0) >= PERMISSION_LEVELS.get(required, 0)


def _now_ms() -> int:
    """返回当前毫秒时间戳。"""
    return int(time.time() * 1000)
