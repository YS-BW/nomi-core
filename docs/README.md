# 📚 Nomi 功能文档

这组文档面向“正在使用或接手 Nomi 的人”，重点讲清楚当前已经落地的功能，而不是把源码结构逐行展开。

统一阅读方式是：

- 先看这个能力能做什么。
- 再看用户应该怎么用。
- 然后看运行边界和注意事项。
- 最后再看相关代码入口。

## 🧭 阅读顺序

第一次接触 Nomi 时，按这个顺序读：

1. [OPERATIONS.md](../OPERATIONS.md)：先把实例跑起来。
2. [INSTANCE.md](./INSTANCE.md)：理解一个 Nomi 实例是什么。
3. [REMOTE.md](./REMOTE.md)：理解 desktop 怎么连 runtime。
4. [WEIXIN.md](./WEIXIN.md)：理解微信入口怎么工作。
5. [TOOLS.md](./TOOLS.md)：理解模型能调用哪些能力。
6. [CRON.md](./CRON.md)：理解自动任务和全局提醒。
7. [INSTANCE_CHANNEL.md](./INSTANCE_CHANNEL.md)：理解两个 Nomi 怎么加好友和聊天。

如果你是开发者，再继续读主链路文档：

- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [RUNTIME.md](./RUNTIME.md)
- [AGENT.md](./AGENT.md)
- [CONTEXT.md](./CONTEXT.md)
- [SESSION.md](./SESSION.md)
- [BUS.md](./BUS.md)

## 🚀 用户入口

| 文档 | 说明 |
|---|---|
| [OPERATIONS.md](../OPERATIONS.md) | 初始化、配置、启动、停止、查看日志和常见操作 |
| [CLI.md](./CLI.md) | `nomi` 命令、交互模式和单次消息模式 |
| [INSTANCE.md](./INSTANCE.md) | 多实例、实例 root、实例 service 和配置隔离 |
| [REMOTE.md](./REMOTE.md) | desktop / remote 的 HTTP + SSE 接入方式 |
| [WEIXIN.md](./WEIXIN.md) | 微信 channel 的登录、启用、收发和分段 |
| [WORKSPACE.md](./WORKSPACE.md) | 工作区文件、启动模板和长期文件布局 |

## 🧠 Agent 能力

| 文档 | 说明 |
|---|---|
| [TOOLS.md](./TOOLS.md) | 文件、搜索、命令、网页、任务、instance、skill、MCP 等工具能力 |
| [CRON.md](./CRON.md) | 自动任务、定时提醒、全局投递和执行边界 |
| [MEMORY.md](./MEMORY.md) | 会话历史、长期记忆、Dream、用户画像 |
| [SKILLS.md](./SKILLS.md) | skill 安装、扫描、注入和使用方式 |
| [COMMAND.md](./COMMAND.md) | 对话里的 slash 命令 |
| [INSTANCE_CHANNEL.md](./INSTANCE_CHANNEL.md) | instance 好友关系、权限和实例间聊天 |

## 🧩 系统结构

| 文档 | 说明 |
|---|---|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 当前整体架构和模块边界 |
| [RUNTIME.md](./RUNTIME.md) | 统一 instance runtime 的生命周期 |
| [AGENT.md](./AGENT.md) | 单轮对话、工具循环、任务执行和后台状态 |
| [CONTEXT.md](./CONTEXT.md) | system prompt、上下文拼装和多模态输入 |
| [SESSION.md](./SESSION.md) | 会话保存、会话 key 和 JSONL 历史 |
| [BUS.md](./BUS.md) | runtime 内部消息总线 |
| [CHANNELS.md](./CHANNELS.md) | 外部 channel 的通用框架 |
| [PROVIDERS.md](./PROVIDERS.md) | 模型 provider、默认模型和配置方式 |
| [STDIO.md](./STDIO.md) | 当前仍保留的 runtime 协议 helper |

## ✅ 当前统一口径

- `instance` 是后台运行主体。
- 一个实例 root 只运行一个统一 runtime。
- `remote` 和 `channel` 是挂在 runtime 上的 adapter。
- `remote/channel` 的 enable/disable 是配置语义，运行中变更需要 `instance restart`。
- 自动任务默认是实例级全局提醒。
- `TOOLS.md` 是 core 内置模板，不再作为每个 workspace 的可变文件生成。
- `nomi-protocol` 是 remote HTTP + SSE 协议事实源。
- desktop 代码位于独立仓库，不在当前 core 仓直接维护。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/cli/app.py](../nomi/cli/app.py#L25-L87) | `nomi` 根命令注册 |
| [nomi/runtime/app.py](../nomi/runtime/app.py#L30-L99) | `NomiRuntime` 创建入口 |
| [nomi/runtime/service/runner.py](../nomi/runtime/service/runner.py#L154-L220) | instance runtime service 前台运行 |
| [nomi/agent/loop.py](../nomi/agent/loop.py#L87-L213) | AgentLoop 装配 |
| [nomi/remote/server.py](../nomi/remote/server.py#L69-L186) | remote HTTP + SSE 服务 |
| [nomi/channel/adapters/weixin/channel.py](../nomi/channel/adapters/weixin/channel.py#L142-L260) | 微信 channel adapter |
