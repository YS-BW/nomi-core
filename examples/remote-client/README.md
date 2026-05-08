# Nomi Remote Client Demo

这是一个 **最小网页版 remote 协议验证器** 🌐

它的角色很单纯：

- 用最小 HTML/CSS/JS 验证 `nomi remote` 的真实链路
- 帮你看清 session、delta、interrupt、task 事件怎么走
- 不承担正式桌面壳 / pet UI 职责

## 能做什么

- 连接 `nomi remote` 的 WebSocket 服务
- 绑定指定 session
- 发送消息并接收流式 `delta`
- 中断当前轮
- 查看 session 列表
- 加载指定 session 的历史消息
- 查看 `status_result`
- 单独显示 `progress` 和 `task_delivered`

## 启动方式

### 1. 启动 remote 服务端

```bash
nomi remote run
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

浏览器原生 WebSocket 不能直接设置 `Authorization` header。

所以这份 demo 当前走的是：

```text
ws://host:port/ws?token=<remote.auth_token>
```

而 remote 服务端仍然保留标准 Bearer Token 主路径：

```text
Authorization: Bearer <remote.auth_token>
```

也就是说：

- 浏览器 demo：走 `?token=...`
- 正式桌面壳 / 非浏览器客户端：优先继续走 `Authorization: Bearer ...`

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
send_message
  -> turn_started
  -> delta*
  -> stream_end*
  -> message
  -> turn_completed
```

任务投递是独立事件：

```text
task_delivered
```

状态和控制类事件：

```text
ready
session_bound
status_result
history_snapshot
session_list
interrupt_result
error
```

## 当前限制

- 只做纯文本显示，不做 Markdown 富文本
- 不做移动端适配
- 不做多会话并排视图
- 不做 pet 动画、角色层、通知气泡系统
- 事件日志默认直接展示原始 JSON，方便调协议
