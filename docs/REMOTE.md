# Remote

Remote 是给 `nomi-desktop` 和其它远程前端使用的实例级 adapter。当前协议已经全量切换为 `HTTP API + SSE Event Stream`：HTTP 负责查询、创建、更新、删除和管理动作，SSE 负责实时 turn 输出、session 变化、任务投递和运行态事件。

当前实现不再提供 `/ws` WebSocket command 面。

## 启动方式

启用 remote 配置：

```bash
nomi remote enable --host 127.0.0.1 --port 8765
nomi remote token
nomi instance restart
```

运行中的 instance 需要重启后才会应用 remote 配置变化。remote 随统一 instance runtime 挂载，不再单独启动进程。

配置字段：

```json
{
  "remote": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 8765,
    "authToken": "..."
  }
}
```

## 鉴权

HTTP API 使用 Bearer token：

```text
Authorization: Bearer <remote.auth_token>
```

SSE 也支持 Bearer token。为了支持浏览器 `EventSource` demo，`GET /v1/events` 额外允许 query token：

```text
GET /v1/events?token=<remote.auth_token>
```

鉴权失败统一返回：

```json
{
  "error": {
    "code": "unauthorized",
    "message": "unauthorized",
    "details": {}
  }
}
```

## 启动流程

远程客户端固定按这个顺序启动：

1. `GET /v1/bootstrap` 拉首屏快照。
2. `GET /v1/events` 建立 SSE。
3. 所有操作走 HTTP API。
4. 所有实时 UI 更新走 SSE reducer。

`bootstrap` 包含：

- `status`
- `sessions`
- `provider_catalog`
- `provider_state`
- `tasks`
- `sidebar`

## HTTP API

基础：

```text
GET /v1/health
GET /v1/bootstrap
GET /v1/status
GET /v1/sidebar
```

Sessions / Turns：

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

发送消息：

```http
POST /v1/sessions/desktop%3Ademo/turns
Authorization: Bearer <token>
Content-Type: application/json

{
  "content": "你好",
  "client_id": "desktop",
  "metadata": {}
}
```

响应只表示已排队：

```json
{
  "turn_id": "turn_xxx",
  "session_id": "desktop:demo",
  "status": "queued"
}
```

后续正文、进度和终态都通过 SSE 返回。

Tasks：

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

任务创建示例：

```json
{
  "instruction": "明早 9 点提醒我量体重",
  "schedule": {
    "kind": "cron",
    "expr": "0 9 * * *",
    "tz": "Asia/Shanghai"
  },
  "source_session_key": "desktop:demo",
  "target_channels": []
}
```

`target_channels` 语义：

- 省略或空数组：全局提醒。
- `["weixin"]`：只投递微信。
- `["cli"]`：只投递 CLI。
- `["remote"]`：只投递 remote / desktop。

Providers / Runtime：

```text
GET   /v1/providers
GET   /v1/providers/state
PATCH /v1/providers/{provider}
PUT   /v1/providers/active
POST  /v1/runtime/reload
POST  /v1/runtime/clear-remote-state
```

Skills：

```text
GET    /v1/skills
POST   /v1/skills/uploads
POST   /v1/skills
DELETE /v1/skills/{skill_name}
```

MCP：

```text
GET    /v1/mcp
POST   /v1/mcp
PATCH  /v1/mcp/{name}
DELETE /v1/mcp/{name}
POST   /v1/mcp/{name}/enable
POST   /v1/mcp/{name}/disable
```

Instance Channel 内部路由：

```text
POST /v1/instance/relations/request
POST /v1/instance/relations/response
POST /v1/instance/messages
```

这三条路由复用 remote listener 和 Bearer token，但属于 core 内部实例通道，不属于 desktop 的 `nomi-protocol` 公开协议面。详情见 [INSTANCE_CHANNEL.md](./INSTANCE_CHANNEL.md)。

## SSE

Endpoint：

```text
GET /v1/events
```

事件 envelope：

```json
{
  "id": "evt_xxx",
  "type": "session.message_appended",
  "created_at_ms": 1780000000000,
  "data": {}
}
```

支持 `Last-Event-ID`。如果短期 buffer 已无法补齐，服务端发送 `runtime.resync_required`，客户端应重新拉 `GET /v1/bootstrap`。

事件类型：

```text
runtime.connected
runtime.status_changed
runtime.reloaded
runtime.resync_required
session.created
session.updated
session.deleted
session.message_appended
turn.started
turn.progress
turn.delta
turn.stream_end
turn.completed
turn.failed
turn.interrupted
task.created
task.updated
task.deleted
task.delivered
provider.state_changed
provider.list_changed
provider.settings_updated
provider.active_changed
sidebar.invalidated
sidebar.snapshot
skill.installed
skill.uninstalled
mcp.created
mcp.updated
mcp.deleted
mcp.enabled
mcp.disabled
```

## 实时 Session 语义

`SessionManager.save()` 会发布 session 保存事件。remote server 订阅后向 SSE 广播：

- `session.message_appended`：新增消息。
- `session.updated`：会话摘要更新。

这条链路对所有 channel 生效，包括 desktop、weixin、CLI 和未来 channel。desktop 打开微信会话时，不应再依赖刷新；只要订阅 SSE，就能收到微信 session 的新增消息。

## 任务投递语义

任务执行结果通过实例级 reminder fanout。remote 收到投递后发送 `task.delivered`。

关键规则：

- `session_id` 表示任务的源会话。
- 全局提醒会投递给所有已运行入口。
- 如果任务设置了 `target_channels` 且不包含 `remote`，desktop 不会收到这条 `task.delivered`。
- 旧 `target_channel / target_chat_id` 不再作为 remote 创建任务的公开投递语义。

## 错误模型

所有 HTTP API 错误统一返回：

```json
{
  "error": {
    "code": "session_not_found",
    "message": "session not found",
    "details": {
      "session_id": "desktop:demo"
    }
  }
}
```

常见状态码：

- `400 invalid_request`
- `401 unauthorized`
- `404 session_not_found / task_not_found / mcp_not_found`
- `409 duplicate_session_id / session_delete_forbidden`
- `500 runtime_error`

## Desktop 接入清单

`nomi-desktop` 需要全量切到 HTTP + SSE：

- 启动时先 `GET /v1/bootstrap`。
- 随后连接 `GET /v1/events`。
- 发消息只调用 `POST /v1/sessions/{session_id}/turns`。
- 历史只调用 `GET /v1/sessions/{session_id}/messages`。
- session、task、provider、skill、MCP 操作全部走 HTTP API。
- reducer 只消费 SSE event，不再消费旧 WebSocket event。
- 当前打开的微信会话必须由 `session.message_appended` 实时追加消息。
- 收到 `runtime.resync_required` 后重新拉 bootstrap。

## Demo

最小浏览器验证器：

```bash
nomi remote enable
nomi instance restart
uv run python -m http.server 8080 -d examples/remote-client
```

打开：

```text
http://127.0.0.1:8080
```

这个 demo 使用 HTTP + SSE，不再使用 WebSocket。

## 代码入口

- Remote server：[nomi/remote/server.py](../nomi/remote/server.py#L69-L277)
- HTTP handlers：[nomi/remote/server.py](../nomi/remote/server.py#L279-L708)
- SSE outbound/session bridge：[nomi/remote/server.py](../nomi/remote/server.py#L710-L818)
- SSE hub：[nomi/remote/events.py](../nomi/remote/events.py#L1-L99)
- Runtime remote facade：[nomi/runtime/app.py](../nomi/runtime/app.py#L334-L714)
- Task HTTP facade：[nomi/runtime/app.py](../nomi/runtime/app.py#L734-L856)
- Session change hook：[nomi/session/manager.py](../nomi/session/manager.py#L296-L345)
- Demo client：[examples/remote-client/app.js](../examples/remote-client/app.js#L1-L491)
