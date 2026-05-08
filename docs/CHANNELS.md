# 🔌 Channel Subsystem

`nomi/channel/` 是外部 channel 子系统的框架层。

可以先把它想成：

> “外部平台怎么接进 Nomi”的统一框架层 🔌

当前产品面已经收口成：

- 用户只看见 `nomi channel` 👀
- 当前只允许一个外部 channel 占用 runtime 🚦
- 当前底层只实现 `weixin` 💬

---

## 目录结构

```text
nomi/channel/
├── base.py
├── registry.py
├── service/
│   ├── login.py
│   ├── runner.py
│   ├── runtime.py
│   ├── state.py
│   └── usecases.py
└── adapters/
    ├── feishu/
    └── weixin/
```

---

## 三层结构

### 1. 抽象层

- `base.py`

定义了：

- `BaseChannel`
- `ChannelRuntimeControl`

它规定一个 channel 至少要实现：

- `login()`
- `start()`
- `stop()`
- `send_message()`
- `send_progress()`
- `send_delta()`

见 [nomi/channel/base.py](../nomi/channel/base.py#L36-L128)。

### 2. 框架层

- `registry.py`
- `service/*`

负责：

- 解析当前 active channel
- 管理 pid/log/state
- 做互斥检查
- 负责前后台启动
- 路由 outbound message

### 3. 平台实现层

- `adapters/weixin/*`

负责：

- 平台登录
- 平台收消息
- 平台发消息
- 平台特有 typing / 媒体 / 协议细节

---

## Registry

当前 registry 只做一件事：根据 `config.channel.kind` 找到 active channel。

对应代码：

- [nomi/channel/registry.py](../nomi/channel/registry.py#L15-L99)

当前关键接口：

- `get_active_channel_kind()`
- `get_active_channel_spec()`
- `get_active_channel_config()`
- `build_active_channel()`
- `get_channel_state_path()`
- `channel_has_login_state()`

### 当前支持情况

配置上预留了：

- `weixin`
- `feishu`

但 registry 当前真正注册的只有：

- `weixin`

见 [nomi/channel/registry.py](../nomi/channel/registry.py#L24-L30)。

---

## Service State

service 状态层负责这些事情：

- pid 文件路径
- log 文件路径
- state 文件路径
- 判断进程是否还活着
- 判断 service 是 `running / stopped / stale`
- 启动前互斥检查
- status 命令快照

对应文件：

- [nomi/channel/service/state.py](../nomi/channel/service/state.py#L28-L313)

### 当前状态文件

默认位置：

```text
~/.nomi/logs/channels-service.pid
~/.nomi/logs/channels-service.log
~/.nomi/logs/channels-service.json
```

### 互斥规则

`ensure_runtime_not_occupied()` 的当前真实语义：

- 如果是 stale，先清理失效 pid/state
- 如果是 running，直接拒绝新的 `run/start/restart`
- 错误提示统一指向 `nomi channel stop`

见 [nomi/channel/service/state.py](../nomi/channel/service/state.py#L244-L256)。

---

## Service Runner

runner 层负责前后台运行。

对应文件：

- [nomi/channel/service/runner.py](../nomi/channel/service/runner.py#L33-L178)

### 当前主要函数

| 函数 | 作用 |
|---|---|
| `build_service_command()` | 构造后台子进程命令 |
| `start_background_service()` | 启动后台 service |
| `stop_background_service()` | 停止后台 service |
| `restart_background_service()` | 重启后台 service |
| `run_active_channel_foreground()` | 前台运行 active channel |
| `follow_log_file()` | 跟随日志文件 |

### 后台启动链路

```text
nomi channel start
  ↓
start_background_service()
  ↓
python -m nomi channel _serve_internal
  ↓
子进程注册 service state
  ↓
父进程确认注册成功
  ↓
写 pid 并输出成功信息
```

这个“等子进程注册后再算成功”的逻辑，是当前避免假成功的关键。

---

## SingleChannelRunner

`SingleChannelRunner` 是“当前唯一 active channel 的运行 owner”。

对应文件：

- [nomi/channel/service/runtime.py](../nomi/channel/service/runtime.py#L18-L127)

它负责：

- 构造当前 active channel 实例
- 启动 outbound dispatch task
- 启动 channel 本身
- 从 bus.outbound 消费消息
- 根据 metadata 选择 `send_progress / send_delta / send_message`

### 当前 outbound 路由规则

| metadata | 走向 |
|---|---|
| `_tool_transition` | `send_progress(..., tool_hint=True)` |
| `_progress` | `send_progress(..., tool_hint=False)` |
| `_stream_delta` / `_stream_end` | `send_delta()` |
| 其它 | `send_message()` |

见 [nomi/channel/service/runtime.py](../nomi/channel/service/runtime.py#L98-L127)。

---

## Login Runtime Stub

登录流程不会拉起完整 runtime，而是用一个极简 stub：

- [nomi/channel/service/login.py](../nomi/channel/service/login.py#L10-L50)

这个 stub 只提供：

- `bus`
- `config`
- `interrupt_session()` 的空实现
- `transcribe_audio()` 的空实现

目的是让 adapter 的 `login()` 能在不启动完整 agent 的情况下复用同一套接口类型。

---

## 当前设计边界

这条边界现在是清楚的：

- `channel/service` 不碰微信协议细节
- `weixin` 不碰 pid / log / 互斥 / service 状态
- CLI 不直接调用 adapter 内部实现
- CLI 只调用 service usecase

如果以后接飞书，也应该沿着这条边界继续加，而不是把平台逻辑再塞回 CLI。
