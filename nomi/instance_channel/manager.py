"""实例关系管理器。"""

from __future__ import annotations

import hashlib
import secrets
import time

from nomi.config.paths import (
    get_instance_invite_path,
    get_instance_relations_path,
    get_instance_requests_path,
)
from nomi.instance_channel.client import InstanceChannelClient
from nomi.instance_channel.models import (
    InstanceInvite,
    InstanceRelation,
    InstanceRelationRequest,
    RelationPermission,
    normalize_key,
    normalize_permission,
)
from nomi.instance_channel.notification import NotificationService
from nomi.instance_channel.store import (
    InstanceInviteStore,
    InstanceRelationRequestStore,
    InstanceRelationStore,
)


class InstanceRelationManager:
    """管理当前 instance 与其它 instance 的申请、关系和权限。"""

    def __init__(
        self,
        *,
        invite_store: InstanceInviteStore | None = None,
        request_store: InstanceRelationRequestStore | None = None,
        relation_store: InstanceRelationStore | None = None,
        notification: NotificationService | None = None,
        client: InstanceChannelClient | None = None,
    ) -> None:
        """装配关系存储、通知和网络 client。"""
        self.invites = invite_store or InstanceInviteStore(get_instance_invite_path())
        self.requests = request_store or InstanceRelationRequestStore(get_instance_requests_path())
        self.relations = relation_store or InstanceRelationStore(get_instance_relations_path())
        self.notification = notification
        self.client = client or InstanceChannelClient()

    def list_relations(self) -> list[InstanceRelation]:
        """列出全部已接受关系。"""
        return self.relations.list()

    def list_requests(self) -> list[InstanceRelationRequest]:
        """列出全部 pending 申请。"""
        return self.requests.list()

    def get_relation(self, key: str) -> InstanceRelation | None:
        """读取单个关系。"""
        return self.relations.get(key)

    def get_request(self, key: str) -> InstanceRelationRequest | None:
        """读取单个 pending 申请。"""
        return self.requests.get(key)

    def build_invite(self, *, key: str, url: str) -> tuple[InstanceInvite, str]:
        """生成新的唯一邀请码并刷新旧邀请码。"""
        normalized_key = normalize_key(key)
        normalized_url = str(url or "").strip().rstrip("/")
        if not normalized_url:
            raise ValueError("invite url is required")
        secret = secrets.token_urlsafe(32)
        invite = InstanceInvite(
            invite_id=f"inv_{secrets.token_urlsafe(12)}",
            secret_hash=_hash_secret(secret),
            url=normalized_url,
            key=normalized_key,
            created_at_ms=_now_ms(),
            used_at_ms=None,
        )
        self.invites.put(invite)
        return invite, secret

    def consume_invite(self, *, invite_id: str, secret: str) -> InstanceInvite:
        """校验并消费当前唯一邀请码。"""
        invite = self.invites.get()
        if invite is None or invite.invite_id != str(invite_id or "").strip():
            raise PermissionError("invalid or expired instance invite")
        if invite.used_at_ms is not None:
            raise PermissionError("instance invite already used")
        if invite.secret_hash != _hash_secret(secret):
            raise PermissionError("invalid instance invite secret")
        return self.invites.mark_used(invite.invite_id, _now_ms())

    def create_incoming_request(
        self,
        *,
        key: str,
        url: str,
        requested_permission: str,
        response_token: str,
        invite_id: str,
    ) -> InstanceRelationRequest:
        """写入一条 incoming pending 申请。"""
        request = InstanceRelationRequest(
            key=normalize_key(key),
            direction="incoming",
            url=str(url or "").strip().rstrip("/"),
            requested_permission=normalize_permission(requested_permission),
            response_token=str(response_token or "").strip(),
            invite_id=str(invite_id or "").strip(),
            created_at_ms=_now_ms(),
        )
        if not request.url or not request.response_token or not request.invite_id:
            raise ValueError("instance request requires url, response_token and invite_id")
        return self.requests.put(request)

    def create_outgoing_request(
        self,
        *,
        key: str,
        url: str,
        requested_permission: str,
        response_token: str,
        invite_id: str,
    ) -> InstanceRelationRequest:
        """写入一条 outgoing pending 申请。"""
        request = InstanceRelationRequest(
            key=normalize_key(key),
            direction="outgoing",
            url=str(url or "").strip().rstrip("/"),
            requested_permission=normalize_permission(requested_permission),
            response_token=str(response_token or "").strip(),
            invite_id=str(invite_id or "").strip(),
            created_at_ms=_now_ms(),
        )
        if not request.url or not request.response_token or not request.invite_id:
            raise ValueError("instance request requires url, response_token and invite_id")
        return self.requests.put(request)

    def accept_incoming(
        self,
        key: str,
        permission: str = "chat",
    ) -> tuple[InstanceRelationRequest, InstanceRelation]:
        """接受 incoming 申请并写入已建立关系。"""
        request = self._require_request(key, direction="incoming")
        relation = self.create_relation(
            key=request.key,
            url=request.url,
            permission=permission,
        )
        self.requests.delete(request.key)
        return request, relation

    def reject_incoming(self, key: str) -> InstanceRelationRequest:
        """拒绝 incoming 申请并删除 pending 记录。"""
        request = self._require_request(key, direction="incoming")
        self.requests.delete(request.key)
        return request

    def accept_outgoing(
        self,
        *,
        key: str,
        url: str,
        relation_id: str,
        relation_token: str,
    ) -> InstanceRelation:
        """申请方处理 accepted 回调并写入关系。"""
        request = self._require_request(key, direction="outgoing")
        relation = InstanceRelation(
            key=request.key,
            url=str(url or request.url).strip().rstrip("/"),
            relation_id=str(relation_id or "").strip(),
            relation_token=str(relation_token or "").strip(),
            permission="chat",
            created_at_ms=_now_ms(),
            updated_at_ms=_now_ms(),
        )
        if not relation.relation_id or not relation.relation_token:
            raise ValueError("relation_id and relation_token are required")
        self.relations.put(relation)
        self.requests.delete(request.key)
        return relation

    def reject_outgoing(self, key: str) -> bool:
        """申请方处理 rejected 回调并删除 pending 记录。"""
        return self.requests.delete(key)

    def withdraw_outgoing(self, key: str) -> InstanceRelationRequest:
        """撤回一条 outgoing 申请并返回删除前快照。"""
        request = self._require_request(key, direction="outgoing")
        self.requests.delete(request.key)
        return request

    def apply_remote_withdraw(self, key: str) -> InstanceRelationRequest:
        """处理对方发来的撤回申请通知。"""
        request = self._require_request(key, direction="incoming")
        self.requests.delete(request.key)
        return request

    def create_relation(self, *, key: str, url: str, permission: str) -> InstanceRelation:
        """创建一条本地已接受关系。"""
        now = _now_ms()
        relation = InstanceRelation(
            key=normalize_key(key),
            url=str(url or "").strip().rstrip("/"),
            relation_id=f"rel_{secrets.token_urlsafe(16)}",
            relation_token=secrets.token_urlsafe(32),
            permission=normalize_permission(permission),
            created_at_ms=now,
            updated_at_ms=now,
        )
        if not relation.url:
            raise ValueError("relation url is required")
        return self.relations.put(relation)

    def remove_relation(self, key: str) -> InstanceRelation:
        """删除一条已建立关系并返回删除前快照。"""
        relation = self._require_relation(key)
        self.relations.delete(relation.key)
        return relation

    def apply_remote_remove(self, relation: InstanceRelation) -> None:
        """处理对方发来的删除关系通知。"""
        self.relations.delete(relation.key)

    def set_permission(self, key: str, permission: str) -> InstanceRelation:
        """更新本地授予对方的权限。"""
        relation = self._require_relation(key)
        relation.permission = normalize_permission(permission)
        relation.updated_at_ms = _now_ms()
        return self.relations.put(relation)

    def require_permission(self, key: str, required: str = "chat") -> InstanceRelation:
        """读取关系并校验权限。"""
        relation = self._require_relation(key)
        if not relation.allows(required):
            raise PermissionError(f"instance relation {key} does not allow {required}")
        return relation

    def require_by_relation_token(
        self,
        *,
        relation_id: str,
        token: str,
        required: str = "chat",
    ) -> InstanceRelation:
        """按 relation_id 和 token 校验请求方身份与权限。"""
        relation = self.relations.find_by_relation_id(relation_id)
        if relation is None or relation.relation_token != str(token or "").strip():
            raise PermissionError("invalid instance relation token")
        if not relation.allows(required):
            raise PermissionError(f"instance relation {relation.key} does not allow {required}")
        return relation

    async def send_invite(
        self,
        *,
        url: str,
        invite_id: str,
        invite_secret: str,
        payload: dict,
        key: str,
        requested_permission: str,
        response_token: str,
    ) -> dict:
        """保存 outgoing 申请并发起好友申请。"""
        request = self.create_outgoing_request(
            key=key,
            url=url,
            requested_permission=requested_permission,
            response_token=response_token,
            invite_id=invite_id,
        )
        result = await self.client.send_relation_request(
            url=request.url,
            invite_id=invite_id,
            secret=invite_secret,
            payload=payload,
        )
        return dict(result or {}) | {"key": request.key, "status": "pending"}

    async def notify_relation_request(self, key: str, requested_permission: str) -> None:
        """通知用户确认关系请求。"""
        if self.notification is None:
            return
        self.notification.enqueue_global(
            notification_id=f"instance_relation_request:{key}",
            content=f"{key} 发来 instance 好友申请，请求 {requested_permission} 权限。",
        )

    async def notify_relation_accepted(self, key: str) -> None:
        """通知用户关系已通过。"""
        if self.notification is None:
            return
        self.notification.enqueue_global(
            notification_id=f"instance_relation_accepted:{key}",
            content=f"已添加 {key}。",
        )

    async def notify_relation_removed(self, key: str) -> None:
        """通知用户对方已解除关系。"""
        if self.notification is None:
            return
        self.notification.enqueue_global(
            notification_id=f"instance_relation_removed:{key}",
            content=f"{key} 已解除与你的 instance 好友关系。",
        )

    async def notify_relation_withdrawn(self, key: str) -> None:
        """通知用户对方已撤回好友申请。"""
        if self.notification is None:
            return
        self.notification.enqueue_global(
            notification_id=f"instance_relation_withdrawn:{key}",
            content=f"{key} 已撤回 instance 好友申请。",
        )

    @staticmethod
    def normalize_permission(permission: str) -> RelationPermission:
        """校验并规范化权限值。"""
        return normalize_permission(permission)

    def _require_request(self, key: str, *, direction: str) -> InstanceRelationRequest:
        """读取指定方向的 pending 申请。"""
        request = self.requests.get(key)
        if request is None:
            raise ValueError(f"instance relation request not found: {key}")
        if request.direction != direction:
            raise ValueError(f"instance relation request {key} is not {direction}")
        return request

    def _require_relation(self, key: str) -> InstanceRelation:
        """读取必需关系。"""
        relation = self.relations.get(key)
        if relation is None:
            raise ValueError(f"instance relation not found: {key}")
        return relation

def _hash_secret(secret: str) -> str:
    """返回邀请码 secret 的哈希。"""
    return hashlib.sha256(str(secret or "").encode("utf-8")).hexdigest()


def _now_ms() -> int:
    """返回当前毫秒时间戳。"""
    return int(time.time() * 1000)
