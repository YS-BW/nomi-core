# Instance Channel

Instance Channel 是实例之间的基础关系与聊天通道。它不是独立 service，也不引入 `peer` 概念；当前实现复用 instance runtime 的 remote HTTP listener。

## 当前语义

当前关系模型固定为：

- `instance.key` 是用户给自己 Nomi 设置的名字，默认由实例名推导，允许中文，但不能包含 `:` 或 `/`。
- `name` 是我给对方 Nomi 的本地备注，只影响展示，不影响关系 key 和 session id。
- 邀请码只用于发起申请，每次生成都会刷新旧邀请码。
- 申请只保存在 pending request 中，接受或拒绝后会删除。
- 接受后才写入 relation，并生成 `relation_id + relation_token`。
- 删除关系时物理删除本地 relation 和 token，并尽力通知对方删除。
- `permission` 只表示“我允许对方对我做什么”，不保存对方授予我的权限。

权限固定为：

- `chat`：允许实例聊天。
- `task`：预留给后续“请求创建任务”能力。
- `all`：预留给后续更高权限动作。

当前第一版只实际使用 `chat` 权限；`task/all` 只作为关系模型和校验框架保留。

## 存储

当前 instance root 下有三类关系文件：

```text
<instance-root>/instance-invite.json
<instance-root>/instance-requests.json
<instance-root>/instance-relations.json
```

`instance-invite.json` 保存当前唯一有效邀请码：

```json
{
  "version": 1,
  "invite_id": "inv_xxx",
  "secret_hash": "sha256...",
  "url": "http://127.0.0.1:8765",
  "key": "default",
  "created_at_ms": 1770000000000,
  "used_at_ms": null
}
```

`instance-requests.json` 只保存 pending 申请：

```json
{
  "version": 1,
  "requests": {
    "xmy": {
      "direction": "incoming",
      "url": "http://127.0.0.1:8766",
      "requested_permission": "chat",
      "response_token": "xxx",
      "invite_id": "inv_xxx",
      "created_at_ms": 1770000000000
    }
  }
}
```

`instance-relations.json` 只保存已接受关系：

```json
{
  "version": 1,
  "relations": {
    "xmy": {
      "name": "小美",
      "url": "http://127.0.0.1:8766",
      "relation_id": "rel_xxx",
      "relation_token": "xxx",
      "permission": "chat",
      "created_at_ms": 1770000000000,
      "updated_at_ms": 1770000000000
    }
  }
}
```

旧版 `token/status` 关系结构不会迁移；缺少 `relation_id/relation_token/url` 的旧关系会 fail-closed。

关键实现：

- [nomi/instance_channel/store.py](../nomi/instance_channel/store.py#L18-L205)
- [nomi/instance_channel/models.py](../nomi/instance_channel/models.py#L17-L156)
- [nomi/config/paths.py](../nomi/config/paths.py#L84-L98)

## 邀请流程

1. A 设置或查看自己的对外 key：

```bash
nomi instance key
nomi instance key 小美
```

2. A 生成一次性邀请码：

```bash
nomi instance invite-code --url http://127.0.0.1:8765
```

邀请码格式：

```text
nomi://instance-invite?v=1&key=<my-key>&url=<url>&invite_id=<id>&secret=<secret>
```

3. B 使用邀请码向 A 申请：

```bash
nomi instance invite --from-code '<invite-code>' --permission chat
```

申请体会携带 B 的 `key/url/requested_permission/response_token`。A 校验 `invite_id + secret` 成功后立即把邀请码标记为已使用，并写入 incoming pending request。

4. A 收到申请后发送实例级全局提醒：

```text
xmy 发来好友申请，请求 chat 权限。可以回复：同意 / 拒绝 / 信任
```

如果当前只有一个待确认申请，用户可以在任意入口直接回复 `同意`、`拒绝` 或 `信任`。这类短回复会在 core 侧确定性处理，不进入模型工具选择；如果同时存在多个待确认申请，必须带上关系 key，例如 `信任 xmy`。

5. A 接受、拒绝、备注、删除或改权限：

```bash
nomi instance accept xmy --permission chat
nomi instance reject xmy
nomi instance rename xmy 小美
nomi instance permission xmy all
nomi instance remove-relation xmy
```

接受后 A 本地生成 `relation_id + relation_token` 并写入 relation，再用申请里的 `response_token` 回调 B。B 收到 accepted 后删除 outgoing request，写入 relation；B 本地授予 A 的 `permission` 默认是 `chat`，之后可自行调整。

核心流程：

- [nomi/runtime/app.py](../nomi/runtime/app.py#L174-L472)
- [nomi/instance_channel/manager.py](../nomi/instance_channel/manager.py#L31-L315)
- [nomi/instance_channel/invite.py](../nomi/instance_channel/invite.py#L12-L42)

## HTTP 通道

Instance Channel 当前复用 remote HTTP listener，因此接收方必须启用 remote：

```bash
nomi remote enable --host 127.0.0.1 --port 8765
nomi instance restart
```

内部 core-only 路由：

```text
POST /v1/instance/relations/request
POST /v1/instance/relations/response
POST /v1/instance/messages
```

鉴权规则：

- `/relations/request` 使用 `X-Nomi-Invite-Id` 和 `Authorization: Bearer <invite-secret>`。
- `/relations/response` 的 accepted/rejected 回调用 `Authorization: Bearer <response-token>`。
- `/relations/response` 的 removed 通知使用 `X-Nomi-Relation-Id` 和 `Authorization: Bearer <relation-token>`。
- `/messages` 使用 `X-Nomi-Relation-Id` 和 `Authorization: Bearer <relation-token>`。
- `remote.auth_token` 只用于 desktop/remote API，不再代表好友身份。

路由入口：

- [nomi/remote/server.py](../nomi/remote/server.py#L740-L786)
- [nomi/instance_channel/client.py](../nomi/instance_channel/client.py#L15-L82)

## 聊天身份

实例消息进入对方 AgentLoop 时使用独立身份：

```text
channel = "instance"
sender_id = "instance:<relation-key>"
session_id = "instance:<relation-key>"
actor = "instance"
```

这样对方实例不会被当成普通用户。对应的 channel prompt 在：

- [nomi/templates/CHANNEL_INSTANCE.md](../nomi/templates/CHANNEL_INSTANCE.md#L1-L5)
- [nomi/agent/context/system_prompt.py](../nomi/agent/context/system_prompt.py#L69-L79)

## Instance 会话

双方都会写入自己的唯一 instance 会话：

```text
instance:<relation-key>
```

发送方在本地写入：

- outbound：我发给对方的消息。
- inbound：对方返回的回复。
- error：HTTP 调用失败时的错误记录。

接收方也写入同一条 `instance:<local-relation-key>` 会话，用户后续问“刚才和哪个 Nomi 聊了什么”时，可由工具读取。关系备注只影响展示名，不改变 session id。

每条 instance 会话消息会带内部 metadata：

```json
{
  "channel": "instance",
  "peer_key": "xmy",
  "direction": "outbound",
  "actor": "self_instance"
}
```

消息执行入口：

- [nomi/runtime/app.py](../nomi/runtime/app.py#L358-L517)

## Agent 工具

当前注册到 runtime 的 instance 关系工具：

- `instance_invite_code`
- `instance_invite`
- `instance_relation_list`
- `instance_relation_accept`
- `instance_relation_reject`
- `instance_relation_remove`
- `instance_relation_set_permission`
- `instance_relation_rename`
- `instance_send_message`
- `instance_session_list`
- `instance_session_get`

工具定义在 [nomi/agent/tools/instance_relations.py](../nomi/agent/tools/instance_relations.py#L19-L363)，由 runtime 在初始化和 reload 后注册：

- [nomi/runtime/app.py](../nomi/runtime/app.py#L1833-L1872)

用户可以在微信、desktop 或 CLI 里自然表达：

```text
生成我的 instance 邀请码，地址用 http://127.0.0.1:8765
用这个邀请码加好友：nomi://instance-invite?...
同意
信任 xmy
备注 xmy 为 小美
删除 xmy 好友
把 xmy 权限改为 all
问一下小美几点方便
你刚才和小美聊了什么
```

## 当前边界

当前第一版不做：

- 自动发现实例。
- 独立 instance relation service。
- 独立端口。
- desktop 协议变更。
- 旧版关系迁移。
- `task_request`、skill/MCP 授权执行。
- 关系冲突自动改名。

如果同一个 key 已存在 relation 或 pending request，新的申请会直接拒绝。删除好友关系会删除本地 relation，并尽力通知对方删除。
