"""实例关系与实例通信工具。"""

from __future__ import annotations

from typing import Any

from nomi.agent.tools.base import Tool, tool_parameters
from nomi.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema


class _InstanceTool(Tool):
    """封装 instance 工具共享依赖。"""

    def __init__(self, runtime: Any) -> None:
        """绑定当前 runtime。"""
        self._runtime = runtime


@tool_parameters(
    tool_parameters_schema(
        required=[],
        description=(
            "生成当前 Nomi instance 的一次性邀请码。"
            "不要传参数；工具会自动使用当前实例 remote 配置里的 host/port。"
        ),
    )
)
class InstanceInviteCodeTool(_InstanceTool):
    """生成当前 instance 邀请码。"""

    @property
    def name(self) -> str:
        """返回工具名。"""
        return "instance_invite_code"

    @property
    def description(self) -> str:
        """返回工具说明。"""
        return "生成当前 Nomi instance 的邀请码，用于让另一个 instance 发起好友申请。"

    @property
    def read_only(self) -> bool:
        """生成邀请码会刷新旧邀请码。"""
        return False

    async def execute(self, public_url: str | None = None, **kwargs: Any) -> str:
        """生成邀请码。"""
        return self._runtime.build_instance_invite_code(public_url or kwargs.get("public_url"))


@tool_parameters(
    tool_parameters_schema(
        required=["invite_code"],
        invite_code=StringSchema("对方 instance 一次性邀请码", min_length=1),
        requested_permission=StringSchema(
            "申请的权限等级，默认 chat",
            enum=["chat", "task", "all"],
            nullable=True,
        ),
    )
)
class InstanceInviteTool(_InstanceTool):
    """向另一个 instance 发起好友申请。"""

    @property
    def name(self) -> str:
        """返回工具名。"""
        return "instance_invite"

    @property
    def description(self) -> str:
        """返回工具说明。"""
        return "通过一次性邀请码向另一个 Nomi instance 发起好友申请。"

    async def execute(
        self,
        invite_code: str,
        requested_permission: str | None = None,
        **kwargs: Any,
    ) -> str:
        """发起好友申请。"""
        del kwargs
        result = await self._runtime.invite_instance(
            invite_code=invite_code,
            requested_permission=requested_permission or "chat",
        )
        return f"已向 {result.get('key') or '对方'} 发送好友申请。"


@tool_parameters(tool_parameters_schema(required=[]))
class InstanceRelationListTool(_InstanceTool):
    """列出当前 instance 关系。"""

    @property
    def name(self) -> str:
        """返回工具名。"""
        return "instance_relation_list"

    @property
    def description(self) -> str:
        """返回工具说明。"""
        return "列出当前 Nomi instance 的好友关系和待处理申请。"

    @property
    def read_only(self) -> bool:
        """关系列表是只读工具。"""
        return True

    async def execute(self, **kwargs: Any) -> str:
        """执行关系列表读取。"""
        del kwargs
        relations = self._runtime.list_instance_relations()
        if not relations:
            return "当前没有 instance 关系。"
        lines = ["当前 instance 关系："]
        for item in relations:
            label = item.get("name") or item["key"]
            direction = item.get("direction") or "-"
            lines.append(
                f"- {item['key']}（{label}）："
                f"{item['status']} / {direction} / {item['permission']} / {item['url']}"
            )
        return "\n".join(lines)


@tool_parameters(
    tool_parameters_schema(
        required=["key"],
        key=StringSchema("关系 key，例如 xmy", min_length=1),
        permission=StringSchema("授权等级", enum=["chat", "task", "all"], nullable=True),
    )
)
class InstanceRelationAcceptTool(_InstanceTool):
    """接受好友申请。"""

    @property
    def name(self) -> str:
        """返回工具名。"""
        return "instance_relation_accept"

    @property
    def description(self) -> str:
        """返回工具说明。"""
        return "接受一个 Nomi instance 好友申请，可指定权限 chat/task/all。"

    async def execute(self, key: str, permission: str | None = None, **kwargs: Any) -> str:
        """执行好友申请接受。"""
        del kwargs
        relation = await self._runtime.accept_instance_relation(key, permission)
        return f"已接受 {relation['key']}，权限：{relation['permission']}。"


@tool_parameters(
    tool_parameters_schema(
        required=["key"],
        key=StringSchema("关系 key，例如 xmy", min_length=1),
    )
)
class InstanceRelationRejectTool(_InstanceTool):
    """拒绝好友申请。"""

    @property
    def name(self) -> str:
        """返回工具名。"""
        return "instance_relation_reject"

    @property
    def description(self) -> str:
        """返回工具说明。"""
        return "拒绝一个 Nomi instance 好友申请。"

    async def execute(self, key: str, **kwargs: Any) -> str:
        """执行好友申请拒绝。"""
        del kwargs
        await self._runtime.reject_instance_relation_async(key)
        return f"已拒绝 {key}。"


@tool_parameters(
    tool_parameters_schema(
        required=["key", "name"],
        key=StringSchema("关系 key，例如 xmy", min_length=1),
        name=StringSchema("备注名", min_length=1),
    )
)
class InstanceRelationRenameTool(_InstanceTool):
    """更新好友备注。"""

    @property
    def name(self) -> str:
        """返回工具名。"""
        return "instance_relation_rename"

    @property
    def description(self) -> str:
        """返回工具说明。"""
        return "给一个 Nomi instance 关系设置或更新备注名。"

    async def execute(self, key: str, name: str, **kwargs: Any) -> str:
        """执行备注更新。"""
        del kwargs
        relation = self._runtime.rename_instance_relation(key, name)
        return f"已把 {relation['key']} 备注为 {relation['name']}。"


@tool_parameters(
    tool_parameters_schema(
        required=["key"],
        key=StringSchema("关系 key，例如 xmy", min_length=1),
    )
)
class InstanceRelationRemoveTool(_InstanceTool):
    """删除好友关系。"""

    @property
    def name(self) -> str:
        """返回工具名。"""
        return "instance_relation_remove"

    @property
    def description(self) -> str:
        """返回工具说明。"""
        return "删除一个已建立的 Nomi instance 好友关系。"

    async def execute(self, key: str, **kwargs: Any) -> str:
        """执行关系删除。"""
        del kwargs
        await self._runtime.remove_instance_relation(key)
        return f"已删除 {key} 的 instance 关系。"


@tool_parameters(
    tool_parameters_schema(
        required=["key", "permission"],
        key=StringSchema("关系 key，例如 xmy", min_length=1),
        permission=StringSchema("授权等级", enum=["chat", "task", "all"]),
    )
)
class InstanceRelationSetPermissionTool(_InstanceTool):
    """修改本地授权。"""

    @property
    def name(self) -> str:
        """返回工具名。"""
        return "instance_relation_set_permission"

    @property
    def description(self) -> str:
        """返回工具说明。"""
        return "修改我允许某个 Nomi instance 对我做什么的权限。"

    async def execute(self, key: str, permission: str, **kwargs: Any) -> str:
        """执行权限修改。"""
        del kwargs
        relation = self._runtime.set_instance_relation_permission(key, permission)
        return f"已把 {relation['key']} 的权限设置为 {relation['permission']}。"


@tool_parameters(
    tool_parameters_schema(
        required=["key", "message"],
        key=StringSchema("目标关系 key，例如 xmy", min_length=1),
        message=StringSchema("要发送给对方 instance 的消息", min_length=1),
    )
)
class InstanceSendMessageTool(_InstanceTool):
    """向另一个 instance 发送消息。"""

    @property
    def name(self) -> str:
        """返回工具名。"""
        return "instance_send_message"

    @property
    def description(self) -> str:
        """返回工具说明。"""
        return "向已成为好友且具备 chat 权限的另一个 Nomi instance 发送消息，并返回对方回复。"

    async def execute(self, key: str, message: str, **kwargs: Any) -> str:
        """发送 instance 消息。"""
        del kwargs
        result = await self._runtime.send_instance_message(key, message)
        return str(result.get("content") or "")


@tool_parameters(
    tool_parameters_schema(
        required=[],
        limit=IntegerSchema(description="最多列出多少条最近 instance 会话", minimum=1, maximum=50),
    )
)
class InstanceSessionListTool(_InstanceTool):
    """列出最近 instance 会话。"""

    @property
    def name(self) -> str:
        """返回工具名。"""
        return "instance_session_list"

    @property
    def description(self) -> str:
        """返回工具说明。"""
        return "列出最近的 Nomi instance 聊天会话，用于回答刚和哪些实例聊过。"

    @property
    def read_only(self) -> bool:
        """会话列表查询不修改状态。"""
        return True

    async def execute(self, limit: int = 10, **kwargs: Any) -> str:
        """读取最近 instance 会话摘要。"""
        del kwargs
        sessions = self._runtime.list_instance_sessions(limit=limit)
        if not sessions:
            return "当前没有 instance 聊天会话。"
        lines = ["最近 instance 会话："]
        for item in sessions:
            label = item.get("name") or item["key"]
            lines.append(
                f"- {item['key']}（{label}）：{item['status']}，"
                f"{item['message_count']} 条消息，最近更新 {item.get('updated_at') or '未知'}"
            )
        return "\n".join(lines)


@tool_parameters(
    tool_parameters_schema(
        required=["key"],
        key=StringSchema("关系 key，例如 xmy", min_length=1),
        limit=IntegerSchema(description="最多读取多少条最近消息", minimum=1, maximum=100),
    )
)
class InstanceSessionGetTool(_InstanceTool):
    """读取某个 instance 会话。"""

    @property
    def name(self) -> str:
        """返回工具名。"""
        return "instance_session_get"

    @property
    def description(self) -> str:
        """返回工具说明。"""
        return "读取某个 Nomi instance 聊天会话的最近消息。"

    @property
    def read_only(self) -> bool:
        """会话读取不修改状态。"""
        return True

    async def execute(self, key: str, limit: int = 20, **kwargs: Any) -> str:
        """读取指定 instance 会话最近消息。"""
        del kwargs
        payload = self._runtime.get_instance_session_messages(key, limit=limit)
        messages = payload.get("messages") or []
        label = payload.get("name") or payload["key"]
        if not messages:
            return f"没有找到 {payload['key']}（{label}）的 instance 聊天记录。"
        lines = [f"{payload['key']}（{label}）最近消息："]
        for item in messages:
            lines.append(f"- {item['label']}：{item['content']}")
        return "\n".join(lines)
