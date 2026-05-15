# ⚙️ Runtime

Runtime 是 Nomi 实例真正运行起来后的核心对象。它把 provider、消息总线、AgentLoop、remote、channel 和任务调度装到同一个进程里。

如果 instance 是“这个 Nomi 个体”，runtime 就是它正在运行的身体。

## 🌟 Runtime 负责什么

Runtime 负责：

- 创建主模型 provider。
- 创建语音转写 provider。
- 创建 MessageBus。
- 创建 AgentLoop。
- 管理 session、tools、tasks、skills、memory。
- 挂载 remote HTTP + SSE adapter。
- 挂载当前启用的 channel adapter。
- 支持 provider reload。
- 暴露状态给 CLI 和 remote。

## 🚀 怎么启动

后台启动默认实例：

```bash
nomi instance start
```

前台运行默认实例：

```bash
nomi instance run
```

重启：

```bash
nomi instance restart
```

停止：

```bash
nomi instance stop
```

## 🧩 启动顺序

实例启动时大致做这些事：

```text
读取 config.json
  ↓
创建 NomiRuntime
  ↓
启动 AgentLoop / task scheduler
  ↓
如果 remote.enabled=true，启动 RemoteServer
  ↓
如果 channel 已启用且登录态可用，启动 channel adapter
  ↓
写入 runtime-service 状态文件
```

这保证同一实例里只有一个 runtime owner。

## 🌐 Remote Adapter

remote 是 desktop 的接入口。

remote 启动条件：

- `remote.enabled = true`
- `remote.authToken` 非空
- host/port 可绑定

remote 不自己创建 runtime，只复用当前实例 runtime。

## 💬 Channel Adapter

channel 是微信这类外部入口。

当前实际可用的是 `weixin`。它启动条件是：

- `channel.kind = "weixin"`
- 微信登录态存在
- 实例 runtime 正在运行

如果 channel 未登录，runtime 可以继续启动，只是 channel adapter 不运行。

## ⏰ 自动任务

TaskRunner 和 CronService 也挂在 runtime 里。

这意味着：

- desktop 创建的任务和微信创建的任务进入同一任务系统。
- 任务触发由同一个 scheduler owner 执行。
- 任务结果通过全局提醒投递给当前运行入口。

## 🔁 Runtime Reload

remote 可以触发 runtime reload，用来应用 provider 配置变化。

reload 后，同一实例里的 remote、channel、task 执行都会使用新的 provider，而不是只有 desktop 侧生效。

## 📄 状态文件

运行时状态写在实例 root 的 `logs/` 目录下：

```text
runtime-service.pid
runtime-service.json
runtime-service.log
```

这些文件用于：

- 查看实例是否运行。
- 查看 remote/channel 是否挂载。
- 查看 scheduler owner。
- 停止或重启进程。

## 🧱 边界

- 一个实例 root 只允许一个 runtime 进程。
- remote/channel 配置变化需要重启实例。
- runtime 不是系统服务管理器；它只管理 Nomi 自己的进程和 adapter。
- 如果旧 remote/channel 独立 service 还活着，新的 instance runtime 会拒绝启动。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/runtime/app.py](../nomi/runtime/app.py#L30-L99) | `NomiRuntime.from_config()` 装配入口 |
| [nomi/runtime/app.py](../nomi/runtime/app.py#L1437-L1452) | runtime start 相关流程 |
| [nomi/runtime/app.py](../nomi/runtime/app.py#L2009-L2035) | reload runtime |
| [nomi/runtime/state.py](../nomi/runtime/state.py#L1-L42) | runtime 状态模型 |
| [nomi/runtime/service/runner.py](../nomi/runtime/service/runner.py#L154-L220) | 前台 runtime service |
| [nomi/runtime/service/state.py](../nomi/runtime/service/state.py#L1-L120) | service pid/json/log 状态 |
| [nomi/remote/server.py](../nomi/remote/server.py#L85-L124) | remote adapter start/stop |
| [nomi/channel/service/runtime.py](../nomi/channel/service/runtime.py#L18-L117) | channel runner |
