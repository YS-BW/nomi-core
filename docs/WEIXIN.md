# 💬 微信 Channel

微信 channel 是 Nomi 当前实际可用的外部聊天入口。它把微信消息转换成 Nomi 的 inbound message，再把 Nomi 回复发回微信。

当前用户可见入口统一是 `nomi channel ...`，channel kind 是 `weixin`。

## 🌟 微信入口能做什么

微信 channel 支持：

- 登录并保存微信状态。
- 接收文本消息。
- 接收图片、语音和文件。
- 语音转写后进入 Agent。
- 把 Agent 回复发送回微信。
- 按 `<part>` 分段发送任务提醒。
- 消费实例级全局提醒。

## 🚀 启用方式

启用微信配置：

```bash
nomi channel enable weixin
```

登录：

```bash
nomi channel login
```

重启实例使配置生效：

```bash
nomi instance restart
```

查看状态：

```bash
nomi channel status
nomi instance status
```

## ⚙️ 配置项

微信配置位于 `config.json` 的 `channel.weixin`：

```json
{
  "channel": {
    "kind": "weixin",
    "weixin": {
      "allowFrom": ["*"],
      "baseUrl": "https://ilinkai.weixin.qq.com",
      "routeTag": null,
      "token": "",
      "stateDir": "",
      "pollTimeout": 35
    }
  }
}
```

常用字段：

| 字段 | 含义 |
|---|---|
| `allowFrom` | 允许哪些微信会话触发 Nomi |
| `baseUrl` | 微信 ilink 服务地址 |
| `token` | 登录 token |
| `stateDir` | 登录态保存目录 |
| `pollTimeout` | 拉取消息超时时间 |

## 📣 分段发送

微信里长回复可以用 `<part>` 分段。

例如模型输出：

```text
第一段<part>第二段<part>第三段
```

微信会按段发送。自动任务提醒也会按 `<part>` 拆分发送。

## ⏰ 自动任务提醒

自动任务默认是全局提醒。如果微信 channel 正在运行且可接收提醒，任务结果会投递到微信。

如果任务设置了 `target_channels=["weixin"]`，则只发微信。

## 📎 媒体处理

微信 channel 会把下载到的媒体保存到实例 media 目录，然后交给 Agent 处理。

语音会通过 runtime 的 transcription provider 转写成文本。

## 🧱 边界

- 当前只支持一个 active channel。
- channel enable 只改配置，启动需要 instance restart。
- 未登录时，runtime 可以启动，但微信 channel 不运行。
- 微信不是单独 runtime owner。
- 微信入口收到的消息也会写入同一套 session 系统。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/cli/commands/channel.py](../nomi/cli/commands/channel.py#L21-L120) | channel CLI |
| [nomi/channel/registry.py](../nomi/channel/registry.py#L24-L99) | channel 注册和登录态判断 |
| [nomi/channel/service/login.py](../nomi/channel/service/login.py#L10-L51) | 登录流程 |
| [nomi/channel/service/runtime.py](../nomi/channel/service/runtime.py#L18-L117) | channel runner |
| [nomi/channel/adapters/weixin/channel.py](../nomi/channel/adapters/weixin/channel.py#L159-L260) | WeixinChannel 初始化和状态目录 |
| [nomi/channel/adapters/weixin/channel.py](../nomi/channel/adapters/weixin/channel.py#L1139-L1200) | 微信发送逻辑和任务分段 |
| [nomi/channel/adapters/weixin/streaming.py](../nomi/channel/adapters/weixin/streaming.py#L15-L212) | 微信流式分段发送 |
