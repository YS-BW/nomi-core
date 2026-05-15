# 🏗️ 整体架构

Nomi 当前的架构可以概括成一句话：

> 一个 instance 对应一个统一 runtime，所有入口都把消息交给同一条 Agent 主链路处理。

入口可以有多个：CLI、desktop remote、微信 channel、instance channel。
但真正持有 session、provider、tools、task scheduler、message bus 的，是同一个 instance runtime。

## 🌟 现在的系统长什么样

```text
InstanceRuntimeService
  ↓
NomiRuntime
  ├─ MessageBus
  ├─ AgentLoop
  ├─ SessionManager
  ├─ Provider
  ├─ ToolRegistry
  ├─ TaskRunner / CronService
  ├─ RemoteAdapter
  ├─ WeixinChannel
  └─ InstanceChannel
```

这意味着：

- CLI、desktop、微信、instance 消息都会进入同一个 runtime。
- 同一实例只有一套 session 和任务调度状态。
- remote 和 channel 不再各自创建独立 runtime。
- provider reload 后，同一实例内所有入口都会使用新的 provider。

## 🚪 入口层

Nomi 当前主要有四类入口：

| 入口 | 用途 |
|---|---|
| CLI | 本地终端对话、实例管理、配置操作 |
| Remote | 给 desktop 使用的 HTTP + SSE adapter |
| Weixin Channel | 微信收发消息入口 |
| Instance Channel | 两个 Nomi 实例之间的关系和聊天通道 |

这些入口不应该各自保存一份任务、会话或 provider 真相。它们只负责把消息带进 runtime，或者把 runtime 的结果带回用户所在的入口。

## ⚙️ Runtime 层

Runtime 是实例级运行主体。

它负责：

- 创建消息总线。
- 创建主模型 provider。
- 创建 AgentLoop。
- 挂载 remote adapter。
- 挂载当前启用的 channel adapter。
- 管理启动、停止、重载和状态文件。

用户看到的 `nomi instance start/run/stop/restart/status/services/log`，管理的就是这一层。

## 🧠 Agent 层

AgentLoop 是一次对话真正发生的地方。

它负责：

- 读取当前 session 历史。
- 拼装 system prompt 和上下文。
- 调用 provider。
- 处理工具调用。
- 保存新消息。
- 写出最终回复。
- 执行自动任务。

从用户视角看，Nomi 像是在不同入口里说话；从内部看，都是 AgentLoop 在处理一轮消息。

## 📨 消息流

典型消息流如下：

```text
用户入口
  ↓
InboundMessage
  ↓
MessageBus
  ↓
AgentLoop
  ↓
Provider / Tools
  ↓
Session 写入
  ↓
OutboundMessage 或 SSE 事件
  ↓
用户入口收到回复
```

remote 和 channel 都是 adapter。它们可以监听 outbound，也可以通过 session event 实时更新 UI，但不应该成为新的 runtime owner。

## ⏰ 自动任务流

自动任务属于 instance 级能力：

```text
用户创建任务
  ↓
tasks.json
  ↓
TaskRunner 派生 cron/jobs.json
  ↓
CronService 到点触发
  ↓
AgentLoop 执行任务指令
  ↓
ReminderStore
  ↓
remote / weixin / cli 按目标消费提醒
```

这里的关键语义是：`tasks.json` 是任务定义真源，`cron/jobs.json` 是派生触发状态。

## 🤝 Instance Channel

Instance Channel 是挂在同一个 runtime 上的内部 HTTP 通道。

它负责：

- 生成一次性邀请码。
- 接收好友申请。
- 建立 relation token。
- 按权限处理 instance 间消息。
- 把 instance 聊天写入唯一的 `instance:<key>` 会话。

它不新开 service，也不引入单独的 peer 概念。

## 🧱 边界

当前架构明确不做这些事：

- 不让 remote 和 channel 各自持有 runtime。
- 不把 desktop 语义写进 core 私有分支。
- 不让自动任务变成系统级后台调度器。
- 不让 channel enable 后热插拔进运行中的 runtime。
- 不把 instance channel 做成额外端口或独立服务。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/runtime/app.py](../nomi/runtime/app.py#L30-L99) | 创建统一 runtime |
| [nomi/runtime/service/runner.py](../nomi/runtime/service/runner.py#L154-L220) | 启动 runtime、remote 和 channel adapter |
| [nomi/agent/loop.py](../nomi/agent/loop.py#L87-L213) | AgentLoop 装配主链路 |
| [nomi/bus/events.py](../nomi/bus/events.py#L8-L37) | inbound / outbound 消息模型 |
| [nomi/bus/queue.py](../nomi/bus/queue.py#L8-L73) | runtime 内部消息总线 |
| [nomi/tasks/runner.py](../nomi/tasks/runner.py#L34-L92) | 任务系统 owner |
| [nomi/remote/server.py](../nomi/remote/server.py#L69-L186) | remote adapter |
| [nomi/channel/service/runtime.py](../nomi/channel/service/runtime.py#L18-L117) | channel runner |
| [nomi/instance_channel/manager.py](../nomi/instance_channel/manager.py#L1-L260) | instance 关系管理 |
