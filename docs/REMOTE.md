# 🌐 Remote

Remote 是 Nomi 给 desktop 和其它远程前端使用的 adapter。当前正式协议是 HTTP API + SSE Event Stream。

HTTP 负责查询、创建、更新和管理动作；SSE 负责实时消息、turn 输出、session 变化、任务提醒和运行态事件。

## 🌟 Remote 能做什么

Remote 提供：

- desktop 启动时拉取 bootstrap。
- 查看 runtime 状态。
- 查看 sidebar 和 sessions。
- 读取会话消息。
- 创建 turn 并通过 SSE 接收回复。
- 创建和管理自动任务。
- 查看和切换 provider。
- 管理 skills 和 MCP。
- 接收 session 实时更新。

## 🚀 启用 Remote

启用配置：

```bash
nomi remote enable --host 127.0.0.1 --port 8765
nomi remote token
nomi instance restart
```

remote 挂在 instance runtime 上，不单独启动进程。

## 🔐 鉴权

HTTP API 使用 Bearer token：

```text
Authorization: Bearer <remote.auth_token>
```

SSE 也支持 Bearer token。为了浏览器 EventSource，`GET /v1/events` 也允许 query token：

```text
GET /v1/events?token=<remote.auth_token>
```

鉴权失败返回统一错误模型。

## 🧭 客户端启动顺序

desktop 启动顺序：

```text
GET /v1/health
  ↓
GET /v1/bootstrap
  ↓
GET /v1/events
  ↓
HTTP API 操作
  ↓
SSE reducer 更新 UI
```

remote 事件是整个 instance 的事件流。desktop 打开微信会话时，也应该通过 session event 实时看到微信消息，而不是依赖手动刷新。

## 📡 主要 API

基础：

```text
GET /v1/health
GET /v1/bootstrap
GET /v1/status
GET /v1/sidebar
GET /v1/events
```

会话：

```text
GET    /v1/sessions
POST   /v1/sessions
GET    /v1/sessions/{session_id}
DELETE /v1/sessions/{session_id}
GET    /v1/sessions/{session_id}/messages
POST   /v1/sessions/{session_id}/turns
POST   /v1/sessions/{session_id}/interrupt
POST   /v1/sessions/{session_id}/reset
```

任务：

```text
GET    /v1/tasks
POST   /v1/tasks
GET    /v1/tasks/{task_id}
PATCH  /v1/tasks/{task_id}
DELETE /v1/tasks/{task_id}
POST   /v1/tasks/{task_id}/enable
POST   /v1/tasks/{task_id}/disable
POST   /v1/tasks/{task_id}/reschedule
```

provider / runtime：

```text
GET   /v1/providers
GET   /v1/providers/state
PATCH /v1/providers/{provider}
PUT   /v1/providers/active
POST  /v1/runtime/reload
POST  /v1/runtime/clear-remote-state
```

skills / MCP：

```text
GET    /v1/skills
POST   /v1/skills/uploads
POST   /v1/skills
DELETE /v1/skills/{skill_name}

GET    /v1/mcp
POST   /v1/mcp
PATCH  /v1/mcp/{name}
DELETE /v1/mcp/{name}
POST   /v1/mcp/{name}/enable
POST   /v1/mcp/{name}/disable
```

## 📣 SSE 事件

SSE 事件覆盖：

- runtime 连接和状态变化。
- session 创建、更新、删除和消息追加。
- turn started / delta / completed / failed。
- task created / updated / deleted / delivered。
- provider 状态变化。
- sidebar invalidated / snapshot。
- skill 和 MCP 变更。

客户端应该把 SSE 当成 UI 实时状态来源。

## ⏰ 任务投递

全局提醒会写入实际 remote session，然后通过 `session.message_appended` 推给 desktop。

如果任务显式设置 `target_channels` 且不包含 `remote`，desktop 不会收到对应提醒。

## 🤝 Instance 内部路由

Remote server 也挂载 instance channel 内部路由：

```text
POST /v1/instance/relations/request
POST /v1/instance/relations/response
POST /v1/instance/messages
```

这些是 core 内部 instance 通道，不属于 desktop remote 协议主面。

## 🧱 边界

- `/ws` WebSocket command 面不再是正式接口。
- Remote 不创建自己的 runtime。
- Remote token 只代表 desktop/remote API 身份，不代表 instance 好友身份。
- 协议事实源是 `nomi-protocol`。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/remote/server.py](../nomi/remote/server.py#L69-L186) | RemoteServer 和路由注册 |
| [nomi/remote/auth.py](../nomi/remote/auth.py#L10-L24) | Bearer/query token 鉴权 |
| [nomi/remote/events.py](../nomi/remote/events.py#L32-L114) | SSE event hub |
| [nomi/runtime/service/runner.py](../nomi/runtime/service/runner.py#L171-L183) | instance runtime 挂载 remote |
| [nomi/cli/commands/remote.py](../nomi/cli/commands/remote.py#L15-L142) | remote CLI |
| [nomi/runtime/app.py](../nomi/runtime/app.py#L1953-L1971) | task/session/sidebar 序列化 |
