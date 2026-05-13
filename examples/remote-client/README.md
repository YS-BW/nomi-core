# Nomi Remote Client Demo

这是一个 **最小网页版 HTTP + SSE remote 协议验证器** 🌐

它的角色很单纯：

- 用最小 HTML/CSS/JS 验证 `nomi remote` 的真实链路
- 帮你看清 session、delta、interrupt、task 事件怎么走
- 不承担正式桌面壳 / pet UI 职责

## 能做什么

- 通过 HTTP 拉取 bootstrap、session 列表和历史
- 通过 HTTP 发送消息、中断当前轮
- 通过 SSE 接收 `turn.delta`、session 变更和 task 事件
- 中断当前轮
- 查看 session 列表
- 加载指定 session 的历史消息
- 查看 `status_result`
- 单独显示 `progress` 和 `task_delivered`

## 启动方式

### 1. 启动 remote 服务端

```bash
nomi remote enable
nomi instance restart
```

### 2. 启动静态文件服务

```bash
uv run python -m http.server 8080 -d examples/remote-client
```

### 3. 打开浏览器

```text
http://127.0.0.1:8080
```

## 鉴权方式

浏览器 `EventSource` 不能直接设置 `Authorization` header。
所以 SSE 连接使用 query token：

```text
http://host:port/v1/events?token=<remote.auth_token>
```

HTTP API 仍使用标准 Bearer Token：

```text
Authorization: Bearer <remote.auth_token>
```

也就是说：

- 浏览器 demo：SSE 走 `?token=...`，HTTP fetch 走 Bearer
- 正式桌面壳 / 非浏览器客户端：HTTP 和 SSE 都优先走 `Authorization: Bearer ...`

## 页面结构

- 左侧：
  - 连接参数
  - session 列表
  - 状态面板
- 右侧：
  - 消息区
  - 事件日志
  - 输入框与发送按钮

## 已验证的事件模型

普通对话期望时序：

```text
POST /v1/sessions/{session_id}/turns
  -> turn.started
  -> turn.delta*
  -> turn.stream_end*
  -> turn.completed
```

任务投递是独立事件：

```text
task.delivered
```

状态和控制类事件：

```text
runtime.connected
session.created / session.updated / session.message_appended
provider.state_changed
sidebar.snapshot
runtime.resync_required
```

## 当前限制

- 只做纯文本显示，不做 Markdown 富文本
- 不做移动端适配
- 不做多会话并排视图
- 不做 pet 动画、角色层、通知气泡系统
- 事件日志默认直接展示原始 JSON，方便调协议
