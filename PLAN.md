# Nomi 后续实现计划

## 0. 当前优先级：Instance Channel 第一阶段

本阶段目标是在 `nomi-core` 内实现 instance 之间的好友关系和基础聊天通道，不引入 `peer` 概念，不修改 `nomi-protocol`，不改 desktop。

当前代码实现状态：代码和测试已完成，真实双实例 smoke 尚未执行。

已完成：

- 新增 `<instance-root>/instance-relations.json` 关系存储。
- 新增 `InstanceRelationManager`，支持 `pending/friend/trusted` 状态和 `chat/task/all` 权限。
- 新增 `NotificationService`，复用现有全局 reminder fanout 发送关系请求和关系通过通知。
- 新增 core 内部 InstanceChannel HTTP 路由：
  - `POST /v1/instance/relations/request`
  - `POST /v1/instance/relations/response`
  - `POST /v1/instance/messages`
- 新增 `nomi instance invite-code/invite/relations/accept/reject/rename/send`。
- 新增 Agent 工具：
  - `instance_relation_list`
  - `instance_relation_accept`
  - `instance_relation_reject`
  - `instance_relation_rename`
  - `instance_send_message`
- instance 消息进入 AgentLoop 时使用 `channel="instance"`、`sender_id="instance:<key>"`、`session_id="instance:<key>"`。
- 补充 `docs/INSTANCE_CHANNEL.md`，并更新 `INSTANCE/REMOTE/TOOLS/README` 文档索引。

当前边界：

- InstanceChannel 共享 remote HTTP listener；接收方必须启用 remote。
- 这三条 `/v1/instance/*` 路由是 core 内部实例通道，不进入 `nomi-protocol`。
- 第一版不做自动发现、独立 service、独立端口、task_request、skill/MCP 授权执行。
- 如果同一 key 已存在但 url/token 不一致，直接拒绝为关系冲突。

已跑测试：

```bash
uv run python -m pytest tests/instance_channel/test_relations.py tests/runtime/test_remote_facade.py tests/remote/test_server.py tests/cli/test_commands.py -q
uv run ruff check nomi/instance_channel nomi/agent/tools/instance_relations.py nomi/runtime/app.py tests/instance_channel/test_relations.py --select F401,F841,I
```

下一步：

1. 运行更完整的 `compileall` 和相关测试。
2. 用两个临时 instance root 做真实 invite/accept/send smoke。
3. smoke 通过后再整理提交。

---

# Nomi Remote Protocol 全量 HTTP + SSE 重构计划

> 本文件替换当前 `PLAN.md`，后续 remote/protocol/desktop 联调相关实现、测试、文档与验收均以这里为准。
> 本轮目标是重构当前 desktop/core remote 协议层，不引入 peer/A2A。

## 1. 目标语义

- `nomi-protocol` 是唯一协议事实源。
- `nomi-core` 只实现协议，不私自发明 wire shape。
- `nomi-desktop` 只消费协议，不手抄 core 字段。
- remote vNext 全量切换为：
  - `HTTP API`：查询、创建、更新、删除、管理动作。
  - `SSE Event Stream`：实时输出、会话变化、任务投递、运行态变化。
- 后端框架固定使用现有 `aiohttp`，不引入 FastAPI / Uvicorn / ASGI 栈。
- 最终形态不保留旧 WebSocket command 面，不做长期兼容层。
- 代码结构必须清晰、可维护、便于后续迭代。
- 必须提供完整接口文档，供 desktop 和后续第三方接入参考。

## 2. 当前问题

当前 remote WebSocket 协议混合了承载：

- request/response 类管理动作；
- turn 流式输出；
- provider/task/sidebar/session 状态推送；
- desktop 当前会话绑定语义。

这导致几个结构问题：

- `list_sessions`、`list_providers`、`task_create_*` 等 CRUD/管理动作被塞进 WS command。
- 响应事件和广播事件混在一条通道里，desktop reducer 难以维护。
- 微信会话、未来其它 channel 会话写入 session 后，desktop 无法实时看到，必须手动刷新。
- 协议持续扩展时容易出现 core/desktop 字段各写一份。

本轮重构必须把协议层从“WS command 大杂烩”收口成“HTTP 管动作，SSE 管事件”。

## 3. 固定架构决策

### 3.1 协议仓

`nomi-protocol` 新增 vNext 结构：

- `shared`：通用模型、错误、分页、session/task/provider/sidebar 类型。
- `http`：HTTP route、request、response schema。
- `events`：SSE event envelope 和全部 event payload。

Python 和 TypeScript 导出必须来自同一份协议定义。

### 3.2 core

`nomi-core` 在现有 `aiohttp` remote server 上挂载：

- `/v1/*` HTTP API；
- `/v1/events` SSE；
- 当前代码已经删除 `/ws` 旧 command 面；
- 后续不得再加回旧 WS command 兼容层。

core 内部新增实例级 remote event hub：

```text
Session write / AgentLoop / TaskRunner / Provider / Resource action
  -> RemoteEventHub
  -> SSE clients
```

关键原则：

- desktop 订阅的是整个 instance 的 session event stream。
- 任何 channel 写入 session，都必须发 `session.message_appended` 和 `session.updated`。
- 不为 weixin、desktop、future peer 做单独特例。

### 3.3 desktop 协作

协议开发和 core vNext 实现完成后，如果需要 desktop 接入，由 core 侧通知 desktop 负责人：

- desktop 负责人 ID：`019e0751-696e-7dd2-bb06-ac90a3ecefdd`
- 要求 desktop 最终全量切到 HTTP + SSE；
- 不保留旧 WebSocket command 兼容逻辑；
- desktop 启动流程改为先 `GET /v1/bootstrap`，再连接 `GET /v1/events`；
- 所有操作改为 HTTP；
- 所有实时 UI 更新改为消费 SSE。

通知时必须附上：

- protocol tag 或本地 protocol 路径；
- core 分支/commit；
- 完整接口文档；
- desktop 验收清单。

## 4. HTTP API 范围

### 4.1 基础

```text
GET /v1/health
GET /v1/bootstrap
GET /v1/status
GET /v1/sidebar
```

`/v1/bootstrap` 返回 desktop 首屏所需完整快照：

- runtime status；
- sessions；
- provider catalog/state；
- tasks；
- sidebar resources。

### 4.2 Sessions / Turns

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

发送消息固定走 HTTP：

```text
POST /v1/sessions/{session_id}/turns
```

返回只表示已排队：

```json
{
  "turn_id": "turn_xxx",
  "session_id": "desktop:xxx",
  "status": "queued"
}
```

后续 `turn.started / turn.delta / turn.completed` 全走 SSE。

### 4.3 Tasks

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

任务创建固定使用当前任务投递语义：

```json
{
  "instruction": "明早 9 点提醒我量体重",
  "schedule": {
    "kind": "cron",
    "expr": "0 9 * * *",
    "tz": "Asia/Shanghai"
  },
  "source_session_key": "desktop:xxx",
  "target_channels": []
}
```

规则：

- `target_channels` 可选。
- 省略或空数组表示全局提醒。
- 指定 `["weixin"]`、`["cli"]`、`["remote"]` 时只投递到指定入口。
- 不向 desktop 暴露旧 `target_channel / target_chat_id` 作为投递语义。

### 4.4 Providers / Runtime

```text
GET   /v1/providers
GET   /v1/providers/state
PATCH /v1/providers/{provider}
PUT   /v1/providers/active
POST  /v1/runtime/reload
POST  /v1/runtime/clear-remote-state
```

### 4.5 Skills

```text
GET    /v1/skills
POST   /v1/skills/uploads
POST   /v1/skills
DELETE /v1/skills/{skill_name}
```

### 4.6 MCP

```text
GET    /v1/mcp
POST   /v1/mcp
PATCH  /v1/mcp/{name}
DELETE /v1/mcp/{name}
POST   /v1/mcp/{name}/enable
POST   /v1/mcp/{name}/disable
```

## 5. SSE Event Stream

### 5.1 Endpoint

```text
GET /v1/events
```

认证继续使用：

```text
Authorization: Bearer <remote_token>
```

支持 `Last-Event-ID`：

- core 保留短期 event buffer；
- 能补齐时从下一条事件继续发送；
- 无法补齐时发送 `runtime.resync_required`；
- desktop 收到后重新拉 `GET /v1/bootstrap`。

### 5.2 Event Envelope

统一 envelope：

```json
{
  "id": "evt_xxx",
  "type": "session.message_appended",
  "created_at_ms": 1780000000000,
  "data": {}
}
```

### 5.3 Event Types

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

## 6. 错误模型

HTTP 错误统一返回：

```json
{
  "error": {
    "code": "session_not_found",
    "message": "session not found",
    "details": {
      "session_id": "weixin:xxx"
    }
  }
}
```

状态码约定：

- `400 invalid_request`
- `401 unauthorized`
- `403 forbidden`
- `404 not_found`
- `409 conflict`
- `422 validation_error`
- `500 internal_error`
- `503 runtime_unavailable`

## 7. 实施阶段

### 阶段一：protocol vNext（代码完成，等待 desktop 联调验收）

在 `nomi-protocol` 完成：

- `shared/http/events` schema；
- Python 导出；
- TypeScript 导出；
- dist 构建；
- protocol README 接口文档；
- 测试覆盖 schema、事件、错误、任务 `target_channels`。

当前 core 使用本地 `nomi-protocol` 联调路径：

```text
/Users/lixinlv/Doing/nomi-protocol
```

### 阶段二：core HTTP + SSE（代码完成，等待 desktop 联调验收）

在 `nomi-core` 完成：

- aiohttp `/v1/*` route；
- `/v1/events` SSE；
- Bearer token 鉴权；
- RemoteEventHub；
- bootstrap 聚合；
- session 写入事件；
- turn 事件；
- task/provider/skill/mcp 事件；
- `/ws` 旧 command 面删除。

core 接口文档在：

```text
docs/REMOTE.md
```

### 阶段三：desktop 接入

core/protocol 阶段完成后，联系 desktop 负责人 `019e0751-696e-7dd2-bb06-ac90a3ecefdd`：

- 要求 desktop 全量切 HTTP + SSE；
- 移除旧 WS command 消费；
- reducer 改成 SSE event 驱动；
- 所有操作改为 HTTP API；
- 当前会话和非当前会话都通过 `session.*` 事件更新。

desktop 验收完成前，不发布最终 protocol tag。

### 阶段四：正式发布与清理

联调通过后：

- 发布 `nomi-protocol` 新 tag；
- `nomi-core` 切正式 tag；
- `nomi-desktop` 切正式 tag；
- 确认 core 仍不暴露旧 `/ws` command 面；
- docs 写入完整接口文档；
- 跑最终回归。

## 8. 测试与验收

### protocol

- Python/TypeScript 导出一致。
- HTTP request/response schema 校验。
- SSE event envelope 和 payload 校验。
- `target_channels` 可选且空数组表示全局。
- 错误模型统一。

### core

- HTTP health/bootstrap/status/sessions/messages/tasks/providers/skills/mcp 全覆盖。
- `POST /v1/sessions/{id}/turns` 返回 queued。
- SSE 收到 `turn.started / turn.delta / turn.completed`。
- 微信会话写入后，SSE 收到 `session.message_appended / session.updated`。
- desktop 不刷新也能看到 weixin session 新消息。
- task 到点后发送 `task.delivered`。
- provider 更新、runtime reload、skill/mcp 变更发送对应事件。
- `Last-Event-ID` 可补发；缺失时发 `runtime.resync_required`。
- HTTP/SSE token 错误返回 401。

### desktop 联调

- desktop 首屏只靠 `/v1/bootstrap` 初始化。
- desktop 发消息只走 HTTP。
- 回复、进度、完成状态只走 SSE。
- 打开微信会话时，微信新消息和回复实时出现。
- desktop 创建任务，到点后 desktop 和微信按全局提醒收到。
- 断线重连后能通过 event cursor 或 bootstrap 恢复。

## 9. 完成定义

本重构只有同时满足下面条件才算完成：

1. `nomi-protocol` vNext schema、Python/TS 导出、dist、测试完成。
2. `nomi-core` HTTP + SSE 实现完成并通过测试。
3. `nomi-desktop` 全量切换到 HTTP + SSE。
4. 旧 WS command 面被移除，不保留长期兼容设定。
5. docs 中有完整接口文档和联调说明。
6. 本文件回写最终状态、剩余风险和验收结果。

## 10. 当前状态与剩余风险

已完成：

- `nomi-protocol` v0.7.0 本地协议模型、Python/TypeScript 导出和 dist。
- `nomi-core` 已切本地 `nomi-protocol` 路径依赖。
- `nomi-core` remote server 已全量切到 `/v1/*` HTTP API + `/v1/events` SSE。
- 旧 `/ws` route 已删除，并增加回归测试防止恢复。
- `session.message_appended` / `session.updated` 已由 session save 统一触发，覆盖 desktop、weixin 和其它 channel。
- remote 浏览器 demo 已切到 HTTP + SSE。

剩余风险：

- desktop 尚未切换到 HTTP + SSE；本阶段不能对外宣称整个 remote 重构完成。
- 当前协议仍是本地路径联调状态，desktop 验收后才能发布正式 `nomi-protocol` tag。
- `runtime.status_changed` 和 `provider.list_changed` 目前是协议保留事件，当前 core 只在实际状态/配置变更路径发送已接入事件。

下一优先级：

1. 通知 desktop 负责人 `019e0751-696e-7dd2-bb06-ac90a3ecefdd` 按 `docs/REMOTE.md` 全量切 HTTP + SSE。
2. desktop 联调通过后发布 `nomi-protocol v0.7.0`。
3. core/desktop 从本地路径依赖切回正式协议版本。
