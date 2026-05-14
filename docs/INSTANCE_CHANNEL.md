# Instance Channel

Instance Channel 是实例之间的基础关系与聊天通道。它不是新的独立 service，也不引入 `peer` 概念；当前实现直接挂在统一 `InstanceRuntime` 上，并复用 remote HTTP listener。

## 当前语义

一个实例可以把另一个实例登记为关系对象。关系状态固定为：

- `pending`：已收到或已发出申请，尚未确认。
- `friend`：已确认好友关系。
- `trusted`：已确认可信任关系。

权限固定为：

- `chat`：允许实例聊天。
- `task`：预留给后续“请求创建任务”能力。
- `all`：预留给后续更高权限动作。

当前第一版只实际使用 `chat` 权限；`task/all` 只作为关系模型和校验框架保留。

## 存储

关系文件位于当前 instance root：

```text
<instance-root>/instance-relations.json
```

结构：

```json
{
  "version": 1,
  "relations": {
    "xmy": {
      "name": "小美",
      "url": "http://127.0.0.1:8766",
      "token": "remote-token",
      "status": "friend",
      "permission": "chat",
      "updated_at_ms": 1770000000000
    }
  }
}
```

关系读写由 `InstanceRelationStore` 负责，并用文件锁保护单文件更新：

- [nomi/instance_channel/store.py](../nomi/instance_channel/store.py#L12-L99)
- [nomi/config/paths.py](../nomi/config/paths.py#L84-L86)

## 邀请流程

1. A 生成邀请码：

```bash
nomi instance invite-code --url http://127.0.0.1:8765
```

邀请码格式：

```text
nomi://instance-invite?name=<instance-name>&url=<url>&token=<remote-token>
```

2. B 使用邀请码向 A 申请，本地 `<key>` 是 B 给 A 设置的关系 key，邀请码里的实例名会先作为备注保存：

```bash
nomi instance invite xmy --from-code '<invite-code>'
```

3. A 收到申请后写入 `pending/chat`，并通过实例级全局提醒通知所有已运行入口：

```text
xmy 想添加你为好友。可以回复：同意添加 xmy / 拒绝 xmy / 信任 xmy
```

4. A 接受、拒绝或设置备注：

```bash
nomi instance accept xmy --permission chat
nomi instance reject xmy
nomi instance rename xmy 小美
```

5. 关系确认后，双方都更新为 `friend` 或 `trusted`，并再次发送全局通知提示设置备注。

核心流程在：

- [nomi/runtime/app.py](../nomi/runtime/app.py#L171-L350)
- [nomi/instance_channel/manager.py](../nomi/instance_channel/manager.py#L19-L143)
- [nomi/instance_channel/invite.py](../nomi/instance_channel/invite.py#L11-L40)

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

这些路由继续使用 `Authorization: Bearer <remote.auth_token>` 鉴权，但不属于 `nomi-protocol` 对 desktop 的公开协议面。

路由入口：

- [nomi/remote/server.py](../nomi/remote/server.py#L177-L179)
- [nomi/remote/server.py](../nomi/remote/server.py#L724-L740)
- [nomi/instance_channel/client.py](../nomi/instance_channel/client.py#L8-L34)

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

消息执行入口：

- [nomi/runtime/app.py](../nomi/runtime/app.py#L352-L385)
- [nomi/agent/loop_runtime/dispatch.py](../nomi/agent/loop_runtime/dispatch.py#L138-L165)

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

接收消息时，如果 `from_key` 和本地关系 key 不一致，runtime 会用 `from_url/from_token` 按 endpoint 匹配已有关系。

## Agent 工具

当前注册到 runtime 的 instance 关系工具：

- `instance_invite_code`
- `instance_invite`
- `instance_relation_list`
- `instance_relation_accept`
- `instance_relation_reject`
- `instance_relation_rename`
- `instance_send_message`
- `instance_session_list`
- `instance_session_get`

工具定义在 [nomi/agent/tools/instance_relations.py](../nomi/agent/tools/instance_relations.py#L19-L311)，由 runtime 在初始化和 reload 后注册：

- [nomi/runtime/app.py](../nomi/runtime/app.py#L1655-L1680)

用户可以在微信、desktop 或 CLI 里自然表达：

```text
生成我的 instance 邀请码，地址用 http://127.0.0.1:8765
用这个邀请码添加 default：nomi://instance-invite?...
同意添加 xmy
备注 xmy 为 小美
问一下小美几点方便
你刚才和小美聊了什么
```

## 当前边界

当前第一版不做：

- 自动发现实例。
- 独立 instance relation service。
- 独立端口。
- desktop 协议变更。
- `task_request`、skill/MCP 授权执行。
- 关系冲突自动改名。

如果同一个 key 已存在但 url/token 不一致，会直接拒绝为关系冲突；如果相同关系重复申请，已有 `friend/trusted` 状态不会被降级回 `pending`。

关系确认回调时，如果对方返回的 `from_key` 和本地 key 不一致，runtime 会优先按 url/token 命中已有关系，避免因为双方命名不同而创建第二条关系。
