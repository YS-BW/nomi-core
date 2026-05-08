# 📨 Bus

Nomi 当前的消息总线非常小，但它很关键 ✉️

因为主链路能解耦，靠的就是这层小总线。

它只有两个 `asyncio.Queue`：

- inbound
- outbound

实现文件：

- [nomi/bus/events.py](../nomi/bus/events.py#L8-L36)
- [nomi/bus/queue.py](../nomi/bus/queue.py#L8-L40)

---

## InboundMessage

定义在 [nomi/bus/events.py](../nomi/bus/events.py#L8-L25)。

当前字段：

| 字段 | 说明 |
|---|---|
| `channel` | 来源通道，例如 `cli`、`weixin` |
| `sender_id` | 发送者标识 |
| `chat_id` | 会话 / 聊天对象标识 |
| `content` | 主文本内容 |
| `timestamp` | 收到消息时间 |
| `media` | 附件或媒体路径列表 |
| `metadata` | 渠道附加元数据 |
| `session_key_override` | 可选会话 key 覆盖 |

### `session_key`

如果没有 override，默认会话 key 就是：

```text
{channel}:{chat_id}
```

对应属性：[nomi/bus/events.py](../nomi/bus/events.py#L21-L25)。

---

## OutboundMessage

定义在 [nomi/bus/events.py](../nomi/bus/events.py#L27-L36)。

当前字段：

| 字段 | 说明 |
|---|---|
| `channel` | 要发送到哪个通道 |
| `chat_id` | 目标聊天对象 |
| `content` | 文本内容 |
| `reply_to` | 可选回复目标 |
| `media` | 附件列表 |
| `metadata` | 附加控制字段 |

---

## 当前 bus 的作用

bus 的作用不是复杂事件系统，而是把几层解耦开：

- 输入层不直接调用 `AgentLoop`
- Agent 不直接写 CLI
- channel 不直接拿 Agent 的内部返回值

典型流向：

```text
CLI / Channel
  ↓ publish_inbound
MessageBus.inbound
  ↓ consume_inbound
AgentLoop
  ↓ publish_outbound
MessageBus.outbound
  ↓ consume_outbound
CLI renderer / Channel runner
```

---

## Metadata 驱动的出站语义

当前很多出站消息不是靠“不同消息类型类”区分，而是靠 `metadata`。

常见标记：

| 标记 | 含义 |
|---|---|
| `_stream_delta` | 正文流式增量 |
| `_stream_end` | 一段流式回复结束 |
| `_streamed` | 本轮最终消息已经通过流式发过 |
| `_progress` | 普通进度提示 |
| `_tool_transition` | 工具切换提示 |

CLI 和 channel runner 都会根据这些 metadata 做不同处理。

例如：

- CLI outbound 消费：[nomi/cli/interactive.py](../nomi/cli/interactive.py#L132-L194)
- channel outbound 路由：[nomi/channel/service/runtime.py](../nomi/channel/service/runtime.py#L98-L127)

---

## Queue API

`MessageBus` 当前 API 很薄：

- `publish_inbound()`
- `consume_inbound()`
- `publish_outbound()`
- `consume_outbound()`
- `inbound_size`
- `outbound_size`

定义在 [nomi/bus/queue.py](../nomi/bus/queue.py#L8-L40)。

---

## 为什么它保持极小很重要

bus 这层越简单越好。

如果把：

- 重试
- 状态机
- channel 特有逻辑
- provider 特有逻辑

都塞进 bus，这层就会变成全局耦合点。

当前 bus 还足够干净，这一点最好继续保持。
