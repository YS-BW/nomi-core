# 🤖 Agent

Agent 是 Nomi 真正“思考、调用工具、回复用户”的主链路。

不同入口发来的消息，最终都会进入 AgentLoop。AgentLoop 会读上下文、调用模型、执行工具、保存会话，再把结果交回入口。

## 🌟 Agent 能做什么

Agent 负责：

- 处理 CLI、desktop、微信、instance 的消息。
- 拼装 system prompt 和历史上下文。
- 调用 provider。
- 处理模型返回的工具调用。
- 保存 session。
- 触发长期记忆整理。
- 执行自动任务。
- 处理 slash command。
- 处理中断和运行态 checkpoint。

## 📨 一轮消息怎么跑

典型流程是：

```text
InboundMessage
  ↓
SessionManager 读取会话
  ↓
ContextBuilder 拼 messages
  ↓
AgentRunner 调 provider
  ↓
模型可能调用 tools
  ↓
TurnProcessor 保存结果
  ↓
OutboundMessage 返回入口
```

如果是 remote 流式对话，delta 会通过 SSE 发给 desktop。

## 🧰 工具调用

模型看到的工具来自 ToolRegistry。

Agent 会做两层控制：

- provider 请求时只暴露当前允许的工具 schema。
- 即使模型返回未授权 tool call，执行层也会拒绝。

instance 来源会按 relation permission 限制工具：

- `chat`：只能 instance 聊天和查询。
- `task`：额外允许 `task_*`。
- `all`：额外允许文件、命令、skill、MCP 和关系工具。

## 🧵 会话串行

同一个 session 的消息会串行执行。
不同 session 可以并行，但会受到全局并发 gate 控制。

这避免同一个会话里两轮回复互相覆盖，也让用户连续补充消息时能进入 pending queue。

## 📝 Slash Command

以 `/` 开头的命令会先走本地 CommandRouter。

例如：

- `/status`
- `/new`
- `/dream`
- `/skill list`
- `/user-review`

这些命令不会发给模型。

## ⏰ 自动任务

自动任务到点后，也会回到 AgentLoop 执行。

这意味着任务不是简单文本闹钟；任务指令可以让 Nomi 调用工具、查询信息、联系另一个 instance，再把结果提醒给用户。

## 🧱 边界

- Agent 不直接管理进程启停，那是 runtime service 的职责。
- Agent 不直接持有 remote/channel socket，只通过 bus 和 adapter 通信。
- instance 来源默认不等于本机用户授权，工具权限必须按 relation 限制。
- 自动任务内部不能递归创建新任务。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/agent/loop.py](../nomi/agent/loop.py#L87-L213) | AgentLoop 初始化和组件装配 |
| [nomi/agent/loop_runtime/dispatch.py](../nomi/agent/loop_runtime/dispatch.py#L20-L73) | bus 消费和消息分发 |
| [nomi/agent/loop_runtime/dispatch.py](../nomi/agent/loop_runtime/dispatch.py#L73-L134) | 单条 inbound 消息执行 |
| [nomi/agent/loop_runtime/dispatch.py](../nomi/agent/loop_runtime/dispatch.py#L135-L203) | direct message 执行 |
| [nomi/agent/execution/processor.py](../nomi/agent/execution/processor.py#L190-L337) | provider/tool loop |
| [nomi/agent/execution/processor.py](../nomi/agent/execution/processor.py#L339-L530) | 单轮消息处理与会话落盘 |
| [nomi/agent/tools/bootstrap.py](../nomi/agent/tools/bootstrap.py#L26-L136) | 默认工具注册 |
| [nomi/tasks/runner.py](../nomi/tasks/runner.py#L782-L920) | scheduled task 执行 |
