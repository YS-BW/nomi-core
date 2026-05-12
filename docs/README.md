# 📚 Nomi Docs

这一组文档只写一件事：把当前已经落地的代码事实讲清楚 🧭

你可以把它理解成：

> 这不是“未来规划册”，而是“现在这套 Nomi 到底怎么工作的说明书” ✍️

写法原则：

- 先讲用户和开发者真正会遇到的主链路 🚶
- 再讲模块边界 🧩
- 最后给源码入口 🔎

如果你刚接手项目，建议按这个顺序读，会轻松很多 👇

1. [README.md](../README.md)
2. [CLI.md](./CLI.md)
3. [ARCHITECTURE.md](./ARCHITECTURE.md)
4. [RUNTIME.md](./RUNTIME.md)
5. [AGENT.md](./AGENT.md)
6. 你当前要改的模块文档
7. 代码

---

## 文档地图

### 入口与使用

| 文档 | 说明 |
|---|---|
| [CLI.md](./CLI.md) | 终端入口、交互循环、快捷键、slash 命令 |
| [INSTANCE.md](./INSTANCE.md) | 实例模型、实例命令组、实例级路径与 service 管理 |
| [WEIXIN.md](./WEIXIN.md) | 微信 channel 的登录、运行、消息收发和分段规则 |
| [REMOTE.md](./REMOTE.md) | 远程 desktop shell 服务、共享协议契约、桌面端接入方式 |
| [WORKSPACE.md](./WORKSPACE.md) | `~/.nomi` 和工作区目录的文件结构 |

另外，正式桌面端代码现在位于独立的 `nomi-desktop` 仓库，不再和当前 Python 主仓同目录维护。

### 主链路

| 文档 | 说明 |
|---|---|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 整体系统图、一级模块分工、主要数据流 |
| [RUNTIME.md](./RUNTIME.md) | `NomiRuntime` 的装配、生命周期和对外 API |
| [AGENT.md](./AGENT.md) | `AgentLoop`、调度、执行、中断、会话落盘 |
| [CONTEXT.md](./CONTEXT.md) | system prompt、runtime block、多模态消息拼装 |
| [SESSION.md](./SESSION.md) | `SessionManager`、JSONL 结构、会话键、checkpoint |
| [BUS.md](./BUS.md) | `InboundMessage` / `OutboundMessage` 和消息队列 |

### 能力子系统

| 文档 | 说明 |
|---|---|
| [MEMORY.md](./MEMORY.md) | `MEMORY.md`、`SOUL.md`、`USER.md`、Dream、画像候选 |
| [TOOLS.md](./TOOLS.md) | 默认工具集合、访问控制、MCP 扩展 |
| [SKILLS.md](./SKILLS.md) | 全局 skills 的扫描、安装、卸载和 prompt 注入 |
| [CRON.md](./CRON.md) | 应用内调度、AI 调用的 cron 工具、触发路径 |
| [COMMAND.md](./COMMAND.md) | slash 命令协议、内置命令、用户画像命令 |
| [PROVIDERS.md](./PROVIDERS.md) | provider 配置、解析规则、后端实现与默认值 |
| [CHANNELS.md](./CHANNELS.md) | 外部 channel 框架层、互斥、service 与 adapter 分层 |
| [REMOTE.md](./REMOTE.md) | 远程 shell bridge、命令/事件协议、后台 service |

### 历史与兼容说明

| 文档 | 说明 |
|---|---|
| [STDIO.md](./STDIO.md) | 当前保留的 runtime 协议辅助层；不属于用户可见 CLI 入口 |

---

## 当前主链路

```text
CLI / Channel
  ↓
MessageBus
  ↓
AgentLoop
  ↓
ContextBuilder + Session + Memory
  ↓
AgentRunner
  ↓
Provider / Tools
  ↓
OutboundMessage
  ↓
CLI 渲染 / Channel 回复
```

对应代码入口：

- CLI 根入口：[nomi/cli/app.py](../nomi/cli/app.py#L25-L87)
- Runtime：[nomi/runtime/app.py](../nomi/runtime/app.py#L30-L332)
- AgentLoop：[nomi/agent/loop.py](../nomi/agent/loop.py#L87-L213)
- 单轮执行：[nomi/agent/execution/processor.py](../nomi/agent/execution/processor.py#L154-L560)
- Provider 装配：[nomi/providers/factory/build.py](../nomi/providers/factory/build.py#L10-L72)

---

## 当前一级目录

```text
nomi/
├── agent/
├── runtime/
├── cli/
├── channel/
├── providers/
├── config/
├── command/
├── session/
├── cron/
├── bus/
├── templates/
└── utils/
```

和现在代码对应的真实子域：

- `agent/context/`：上下文与消息组装
- `agent/execution/`：单轮执行与 tool loop
- `agent/loop_runtime/`：分发、并发控制、后台运行态
- `agent/memory/`：记忆、Dream、用户画像
- `agent/tools/`：默认工具与 MCP
- `runtime/service/`：实例级 runtime service 的状态、前后台运行
- `channel/service/`：channel 登录 stub 与 adapter runner
- `channel/adapters/weixin/`：微信平台协议 owner

---

## 当前要特别注意的事实

- `nomi channel` 才是现在对外的 channel 入口，不要再按旧命令理解 🚫
- 用户可见外部入口是 `nomi channel`，不是旧的 `channels` / `serve`
- 桌面壳相关入口现在是 `nomi remote`，它不属于 `channel`
- 配置结构是 `channel.kind + channel.weixin + channel.feishu`，不是旧的 `channels.weixin`
- 远程服务配置固定在 `remote.enabled + remote.host + remote.port + remote.auth_token`
- `USER.md` 现在有“候选抽取 -> 用户确认 -> 写回”的完整链路
- 微信分段当前依赖模型输出 `<part>`，channel 自己只负责按 `<part>` flush
- `nomi agent` 不参与 channel 互斥
- `STDIO` 相关代码还在 runtime 协议层，但当前不作为正式 CLI 入口暴露

---

## 文档约束

这套文档默认只写“已经存在并可验证的行为”。

如果你改了代码，正常应该同步回写：

- 本文件
- 对应模块文档
- 根 `README.md`

否则后续接手的人会直接被误导。
