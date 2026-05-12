# 🔌 Channel Subsystem

`nomi/channel/` 是外部 channel 子系统的框架层。

可以先把它想成：

> “外部平台怎么接进 Nomi”的统一框架层 🔌

当前产品面已经收口成：

- 用户只看见 `nomi channel` 👀
- 当前只允许一个 active channel 挂载到实例 runtime 🚦
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
- 提供登录 runtime stub
- 运行 active channel adapter
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

## 启动模型

channel 不再是独立后台 service。

当前启动链路是：

```text
nomi instance start
  ↓
InstanceRuntimeService
  ↓
NomiRuntime
  ↓
SingleChannelRunner
  ↓
WeixinChannel
```

channel CLI 只负责配置、登录和状态：

- `nomi channel enable weixin`
- `nomi channel disable`
- `nomi channel login`
- `nomi channel status`

配置变化通过 `nomi instance restart` 生效。

---

## SingleChannelRunner

`SingleChannelRunner` 是“当前唯一 active channel 的运行 owner”。

对应文件：

- [nomi/channel/service/runtime.py](../nomi/channel/service/runtime.py#L18-L127)

它负责：

- 构造当前 active channel 实例
- 启动 channel 本身
- 订阅 runtime bus 的 outbound 消息
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
- `weixin` 不碰 instance runtime 的 pid / log / service 状态
- CLI 不直接调用 adapter 内部实现
- CLI 只做配置、登录和状态入口

如果以后接飞书，也应该沿着这条边界继续加，而不是把平台逻辑再塞回 CLI。
