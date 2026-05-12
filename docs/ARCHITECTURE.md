# 🏗️ Architecture

Nomi 当前的整体结构可以概括成一句话：

> 一个统一的进程内 runtime，承载一个真实的 Agent 主链路；CLI 和外部 channel 都只是这个主链路的不同入口。⚙️🤖

如果只想先抓重点，可以把它想成：

> “前面有很多入口，但后面其实都汇到同一台发动机里。” 🚇

---

## 一级模块分工

| 模块 | 职责 |
|---|---|
| `nomi/cli` | 用户命令入口、交互循环、终端渲染 |
| `nomi/runtime` | runtime 装配、生命周期、对外控制 API |
| `nomi/agent` | Agent 主链路、上下文、执行、记忆、tools、skills |
| `nomi/channel` | 单入口外部 channel 子系统 |
| `nomi/providers` | provider 注册表、解析、后端适配 |
| `nomi/config` | 配置模型、加载、路径规则 |
| `nomi/command` | slash 命令路由和 handlers |
| `nomi/session` | 会话持久化 |
| `nomi/cron` | 应用内调度 |
| `nomi/bus` | 入站 / 出站消息总线 |
| `nomi/templates` | prompt 模板和工作区模板 |
| `nomi/utils` | 低层辅助工具 |

如果只看感觉，可以这么理解：

- `cli` 是门口 🚪
- `runtime` 是发动机 ⚙️
- `agent` 是大脑 🧠
- `channel` 是外部接线口 🔌

---

## 当前主链路

### CLI 入口

```text
nomi / nomi agent
  ↓
NomiRuntime
  ↓
MessageBus
  ↓
AgentLoop
  ↓
TurnProcessor / AgentRunner
  ↓
Provider / Tools
  ↓
OutboundMessage
  ↓
CLI renderer
```

关键入口：

- CLI app：[nomi/cli/app.py](../nomi/cli/app.py#L25-L87)
- agent 命令：[nomi/cli/commands/agent.py](../nomi/cli/commands/agent.py#L23-L128)
- interactive loop：[nomi/cli/interactive.py](../nomi/cli/interactive.py#L54-L313)
- runtime：[nomi/runtime/app.py](../nomi/runtime/app.py#L30-L332)

### Channel 入口

```text
nomi instance start
  ↓
instance runtime service
  ↓
NomiRuntime
  ↓
SingleChannelRunner
  ↓
WeixinChannel
  ↓
MessageBus
  ↓
AgentLoop
  ↓
MessageBus
  ↓
SingleChannelRunner outbound dispatch
  ↓
WeixinChannel reply
```

关键入口：

- CLI channel 命令：[nomi/cli/commands/channel.py](../nomi/cli/commands/channel.py#L24-L103)
- channel usecases：[nomi/channel/service/usecases.py](../nomi/channel/service/usecases.py#L26-L74)
- runner：[nomi/channel/service/runtime.py](../nomi/channel/service/runtime.py#L18-L127)
- weixin adapter：[nomi/channel/adapters/weixin/channel.py](../nomi/channel/adapters/weixin/channel.py#L142-L837)

---

## 当前 `agent/` 的内部结构

`agent/` 不再是一个“大杂烩目录”，而是拆成了几个明确子域：

```text
nomi/agent/
├── context/
│   ├── builder.py
│   ├── runtime_blocks.py
│   ├── system_prompt.py
│   └── message_codec.py
├── execution/
│   ├── runner.py
│   ├── processor.py
│   ├── messages.py
│   ├── tokens.py
│   └── tool_results.py
├── loop_runtime/
│   ├── state.py
│   ├── control.py
│   ├── dispatch.py
│   └── background.py
├── memory/
│   ├── store.py
│   ├── consolidator.py
│   ├── dream.py
│   ├── autocompact.py
│   └── profile.py
├── skills/
├── tools/
├── hook.py
└── loop.py
```

核心关系：

- `loop.py` 是 façade
- `execution/processor.py` 是单轮执行 owner
- `execution/runner.py` 是 provider/tool loop owner
- `context/` 只做消息和 prompt 组装
- `memory/` 只做长期记忆与画像逻辑

对应代码：

- AgentLoop 装配：[nomi/agent/loop.py](../nomi/agent/loop.py#L92-L213)
- ContextBuilder：[nomi/agent/context/builder.py](../nomi/agent/context/builder.py#L20-L148)
- TurnProcessor：[nomi/agent/execution/processor.py](../nomi/agent/execution/processor.py#L154-L560)

---

## 当前 `channel/` 的内部结构

`channel/` 现在有很明确的“框架层 / 平台层”分离：

```text
nomi/channel/
├── base.py
├── registry.py
├── service/
│   ├── state.py
│   ├── runner.py
│   ├── runtime.py
│   ├── login.py
│   └── usecases.py
└── adapters/
    ├── feishu/
    └── weixin/
        ├── channel.py
        ├── streaming.py
        └── filter.py
```

分工：

- `registry.py`：解析当前 active channel kind
- `service/login.py`：登录流程使用的极简 runtime stub
- `service/runtime.py`：SingleChannelRunner + outbound 路由
- `adapters/weixin/`：微信协议实现

关键代码：

- registry：[nomi/channel/registry.py](../nomi/channel/registry.py#L15-L99)
- runtime runner：[nomi/channel/service/runtime.py](../nomi/channel/service/runtime.py#L18-L127)

---

## 当前 `providers/` 的内部结构

`providers/` 也已经收口成了三层：

```text
nomi/providers/
├── base.py
├── factory/
│   ├── registry.py
│   ├── resolution.py
│   ├── build.py
│   └── model_catalog.py
├── backends/
│   ├── openai_compat.py
│   ├── anthropic.py
│   └── azure_openai.py
├── openai_compat/
└── capabilities/
```

分工：

- `factory/registry.py`：provider 规格表
- `factory/resolution.py`：根据配置和模型名解析 provider
- `factory/build.py`：真正实例化 backend
- `backends/`：各类 provider 实现

---

## 运行时目录

当前运行时根目录默认是：

```text
~/.nomi
```

主要内容：

```text
~/.nomi/
├── config.json
├── history/
├── logs/
├── skills/
├── weixin/
└── workspace/
```

路径逻辑在 [nomi/config/paths.py](../nomi/config/paths.py#L10-L65)。

---

## 设计边界

当前架构里有几条边界是必须记住的：

- `runtime` 负责装配和生命周期，不写 CLI 渲染逻辑
- `cli` 负责参数解析和输出，不负责业务拼装
- `agent/context` 不直接写记忆文件
- `channel/service` 不写微信协议细节
- `weixin` adapter 不负责全局互斥和 pid 状态
- `MemoryStore` 只负责文件事实，不负责模型决策
- `UserProfileService` 负责画像候选抽取和确认，不直接管理 CLI 命令

如果后续改代码打破这些边界，维护成本会立刻升高。
