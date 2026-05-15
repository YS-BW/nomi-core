# 🔌 Channels

Channel 是外部聊天平台接入 Nomi 的 adapter 层。当前正式可用的 channel 是微信。

Channel 不持有自己的 runtime。它挂在 instance runtime 上，把外部消息转成 `InboundMessage`，再把 Nomi 的 `OutboundMessage` 发回平台。

## 🌟 Channel 层负责什么

Channel 层负责：

- 平台登录。
- 拉取或接收平台消息。
- 下载媒体文件。
- 转成 Nomi 标准 inbound message。
- 发送最终回复。
- 发送流式 delta 或分段消息。
- 消费实例级提醒。

## 🧩 当前支持的 Channel

| kind | 状态 |
|---|---|
| `weixin` | 当前实际可用 |

当前只支持一个 active channel。

## 🚀 使用方式

启用微信 channel：

```bash
nomi channel enable weixin
nomi channel login
nomi instance restart
```

查看状态：

```bash
nomi channel status
```

## 📨 消息流

```text
外部平台消息
  ↓
Channel adapter
  ↓
InboundMessage
  ↓
MessageBus
  ↓
AgentLoop
  ↓
OutboundMessage
  ↓
Channel adapter
  ↓
外部平台
```

## 📣 和全局提醒

运行中的 channel 会注册成提醒 consumer。

自动任务完成后，如果目标包含该 channel，channel 会消费提醒并发送到平台。

## 🧱 边界

- Channel enable/disable 是配置动作。
- 运行中配置变化需要 `nomi instance restart`。
- Channel 不再单独启动 runtime。
- Channel 不负责 provider reload。
- Channel 只处理自己的 outbound message。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/channel/base.py](../nomi/channel/base.py#L39-L131) | channel 基础抽象 |
| [nomi/channel/registry.py](../nomi/channel/registry.py#L15-L99) | channel 注册表 |
| [nomi/channel/service/runtime.py](../nomi/channel/service/runtime.py#L18-L117) | SingleChannelRunner |
| [nomi/runtime/service/runner.py](../nomi/runtime/service/runner.py#L171-L185) | instance runtime 挂载 channel |
| [nomi/channel/adapters/weixin/channel.py](../nomi/channel/adapters/weixin/channel.py#L159-L260) | 微信 adapter |
