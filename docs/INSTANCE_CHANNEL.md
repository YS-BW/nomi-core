# 🤝 Instance Channel

Instance Channel 是两个 Nomi 实例之间的关系和聊天通道。它不引入新的 peer 概念，也不启动独立服务；它复用当前 instance runtime 的 remote HTTP listener。

## 🌟 它能做什么

Instance Channel 支持：

- 为当前 Nomi 设置名字。
- 生成一次性邀请码。
- 用邀请码发起好友申请。
- 接受、拒绝、撤回申请。
- 删除好友关系。
- 设置授予对方的权限。
- 向另一个 instance 发送消息并等待回复。
- 查询本机 instance 会话历史。

## 🪪 名字和邀请码

`instance.key` 是用户给自己 Nomi 设置的名字，默认是 `nomi`。

设置名字：

```bash
nomi instance key 小美
```

生成邀请码：

```bash
nomi instance invite-code
```

邀请码格式：

```text
nomi://instance-invite?v=1&key=<my-key>&url=<url>&invite_id=<id>&secret=<secret>
```

每次生成都会刷新旧邀请码。邀请码只能被成功使用一次。

## 📨 好友申请流程

典型流程：

```text
A 生成邀请码
  ↓
B 使用邀请码发起申请
  ↓
A 收到全局提醒
  ↓
A 接受或拒绝
  ↓
接受后双方写入 relation
  ↓
双方可以聊天
```

CLI 示例：

```bash
nomi instance invite-code
nomi instance invite --from-code "nomi://instance-invite?..."
nomi instance accept xmy --permission chat
nomi instance send xmy "你现在方便吗？"
```

## 🔐 权限

权限只表示“我允许对方在我的 runtime 里做什么”。

| 权限 | 含义 |
|---|---|
| `chat` | 允许 instance 聊天和查询 instance 会话 |
| `task` | 在 `chat` 基础上允许 `task_*` 工具 |
| `all` | 在 `task` 基础上允许文件、命令、skill、MCP 和关系管理工具 |

权限保存在本机 relation 中，不保存对方授予我的权限。

修改权限：

```bash
nomi instance permission xmy task
```

## 💬 聊天和会话

给另一个实例发消息：

```bash
nomi instance send xmy "你今天有什么安排？"
```

双方都会写入自己的 instance 会话：

```text
instance:<relation_key>
```

用户问“你刚才和哪个 Nomi 聊了什么”时，模型会用 `instance_session_list` 和 `instance_session_get` 查询这些历史。

## 📣 好友通知

收到好友申请或关系建立后，Nomi 会用本机模型生成自然提醒，再走全局通知投递给用户。

这类通知用于关系建立，不是让远端 instance 任意主动询问本机用户。

## 🧱 边界

- Instance Channel 要求 remote listener 正在运行。
- Remote token 不代表好友身份。
- 好友消息使用 `relation_id + relation_token` 鉴权。
- 当前不做自动发现，不扫描局域网。
- 删除关系会物理删除本地 relation 和 token。
- instance 会话不会主动向本机用户发开放式问题。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/instance_channel/models.py](../nomi/instance_channel/models.py#L1-L120) | invite、request、relation、permission 模型 |
| [nomi/instance_channel/store.py](../nomi/instance_channel/store.py#L18-L216) | 关系文件存储 |
| [nomi/instance_channel/manager.py](../nomi/instance_channel/manager.py#L1-L260) | 申请、接受、删除、权限管理 |
| [nomi/instance_channel/client.py](../nomi/instance_channel/client.py#L8-L82) | 调用对方 instance HTTP 路由 |
| [nomi/agent/tools/instance_relations.py](../nomi/agent/tools/instance_relations.py#L11-L408) | Agent instance 工具 |
| [nomi/runtime/app.py](../nomi/runtime/app.py#L488-L658) | 关系请求和通知处理 |
| [nomi/runtime/app.py](../nomi/runtime/app.py#L660-L760) | instance 消息执行和会话写入 |
| [nomi/remote/server.py](../nomi/remote/server.py#L177-L185) | instance channel HTTP 路由挂载 |
