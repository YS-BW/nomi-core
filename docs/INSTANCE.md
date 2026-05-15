# 🧩 Instance

Instance 是 Nomi 的运行单位。一个 instance 有自己的配置、会话、工作区、skills、日志、微信状态和 instance 关系。

你可以把它理解成“一个独立的 Nomi 个体”。

## 🌟 Instance 解决什么问题

Instance 让你可以：

- 在同一台机器上运行多个 Nomi。
- 给不同 Nomi 使用不同配置和端口。
- 隔离会话历史、自动任务和 skills。
- 让每个 Nomi 有自己的名字和好友关系。
- 用统一 runtime 管理 remote、channel 和 task scheduler。

## 📁 默认实例

默认实例名是：

```text
default
```

默认实例 root 是：

```text
~/.nomi
```

不传实例名时，大多数命令都会作用到默认实例。

## 🗂️ 实例目录

一个实例 root 通常包含：

```text
<instance-root>/
├── config.json
├── workspace/
├── sessions/
├── skills/
├── logs/
├── media/
├── history/
├── weixin/
├── instance-invite.json
├── instance-requests.json
└── instance-relations.json
```

这些文件共同构成当前实例的运行事实。

## 🚀 常用命令

默认实例：

```bash
nomi instance start
nomi instance status
nomi instance log
nomi instance restart
nomi instance stop
```

命名实例：

```bash
nomi instance create xmy
nomi instance start xmy
nomi instance status xmy
nomi instance stop xmy
```

查看所有实例服务：

```bash
nomi instance services
```

## ⚙️ Runtime 语义

一个实例 root 只允许一个 runtime 进程。

这个 runtime 统一持有：

- provider
- AgentLoop
- session
- tools
- task scheduler
- MessageBus
- remote adapter
- channel adapter

因此同一实例里的 desktop、微信和 CLI 不再各自维护独立任务状态。

## 🌐 Remote 和 Channel

remote 和 channel 都是 instance runtime 上的 adapter。

配置它们：

```bash
nomi remote enable --host 127.0.0.1 --port 8765
nomi channel enable weixin
nomi instance restart
```

enable/disable 只改配置。运行中的实例需要重启后才会应用。

## 🪪 Instance 名字

每个实例可以设置自己的名字：

```bash
nomi instance key
nomi instance key 小美
```

模型里也有 `instance_set_name` 工具，所以用户可以自然说：

```text
你现在就叫小美。
```

名字会用于 instance 好友申请和 instance 间沟通。

## 🤝 Instance 关系

Instance 可以生成邀请码，让另一个 instance 发起好友申请：

```bash
nomi instance invite-code
nomi instance invite --from-code "nomi://instance-invite?..."
nomi instance accept xmy --permission chat
```

关系建立后，可以发送消息：

```bash
nomi instance send xmy "你现在方便吗？"
```

详细设计见 [INSTANCE_CHANNEL.md](./INSTANCE_CHANNEL.md)。

## 🧱 边界

- Instance 不是单独的用户账号系统。
- 当前不做自动发现，不扫描局域网。
- 当前只支持一个 active channel。
- remote 端口冲突时不会自动换端口。
- 修改配置后需要重启实例，不做 adapter 热插拔。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/config/instance.py](../nomi/config/instance.py#L13-L258) | 实例解析、注册和路径初始化 |
| [nomi/config/paths.py](../nomi/config/paths.py#L15-L118) | 实例级路径派生 |
| [nomi/config/schema/instance.py](../nomi/config/schema/instance.py#L1-L26) | `instance.key` 配置 |
| [nomi/cli/commands/instance.py](../nomi/cli/commands/instance.py#L37-L497) | instance CLI 命令组 |
| [nomi/runtime/service/runner.py](../nomi/runtime/service/runner.py#L154-L220) | instance runtime service |
| [nomi/runtime/app.py](../nomi/runtime/app.py#L30-L99) | runtime 装配 |
| [nomi/instance_channel/manager.py](../nomi/instance_channel/manager.py#L1-L260) | instance 关系管理 |
