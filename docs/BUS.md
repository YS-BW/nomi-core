# 📨 Message Bus

MessageBus 是 runtime 内部的消息管道。入口把消息放进 inbound，Agent 处理完后把结果发到 outbound，adapter 再把结果送回用户。

它很小，但它让 CLI、remote、channel 和 AgentLoop 不需要直接耦合。

## 🌟 Bus 做什么

Bus 负责：

- 接收入口发来的 `InboundMessage`。
- 暂存 Agent 产出的 `OutboundMessage`。
- 支持 outbound subscriber fanout。
- 让 remote 和 channel 可以并列监听输出。

## 📥 InboundMessage

InboundMessage 表示一条进入 Agent 的消息。

常见字段：

| 字段 | 含义 |
|---|---|
| `channel` | 来源入口，例如 `cli`、`weixin`、`remote`、`instance` |
| `sender_id` | 发送者标识 |
| `chat_id` | 当前聊天对象 |
| `content` | 文本内容 |
| `media` | 图片或文件路径 |
| `metadata` | 入口附加信息 |
| `session_key_override` | 可选会话 key 覆盖 |

默认会话 key 是：

```text
{channel}:{chat_id}
```

## 📤 OutboundMessage

OutboundMessage 表示 Agent 要发回某个入口的内容。

常见字段：

| 字段 | 含义 |
|---|---|
| `channel` | 目标入口 |
| `chat_id` | 目标聊天对象 |
| `content` | 回复文本 |
| `reply_to` | 可选回复目标 |
| `media` | 附件 |
| `metadata` | 流式、任务、事件等附加信息 |

## 📣 Outbound Fanout

当前 outbound 支持 subscriber。

这对统一 runtime 很关键：

- remote 可以订阅 outbound，把结果变成 SSE/session event。
- channel 可以订阅 outbound，只处理属于自己的消息。
- 不再要求只有一个 consumer 独占 outbound queue。

## ⏰ 和全局提醒

自动任务结果会先进入实例级 reminder store。
各入口在运行时消费提醒，再把提醒写成自己的 outbound/session 事件。

Bus 只负责运行时消息流，不是持久化提醒队列。

## 🧱 边界

- Bus 是进程内机制，不是跨进程消息队列。
- Bus 不负责保存历史，历史由 SessionManager 保存。
- Bus 不负责鉴权，鉴权在 remote/channel/instance channel 层处理。
- Bus 不应该承载任务定义真相，任务定义在 `tasks.json`。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/bus/events.py](../nomi/bus/events.py#L8-L37) | InboundMessage / OutboundMessage |
| [nomi/bus/queue.py](../nomi/bus/queue.py#L8-L73) | MessageBus 队列和 subscriber |
| [nomi/agent/loop_runtime/dispatch.py](../nomi/agent/loop_runtime/dispatch.py#L34-L73) | AgentLoop 消费 inbound |
| [nomi/remote/server.py](../nomi/remote/server.py#L85-L124) | remote 订阅 outbound |
| [nomi/channel/service/runtime.py](../nomi/channel/service/runtime.py#L18-L117) | channel runner 消费输出 |
