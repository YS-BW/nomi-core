# 💻 CLI

CLI 是 Nomi 当前最主要、也是你最常接触到的入口 ⌨️

它不只是“命令分发器”，而是真正的用户交互层：

- 负责解析 root 命令和子命令 🧭
- 负责交互循环 🔄
- 负责流式输出渲染 ✨
- 负责把用户输入变成 `InboundMessage` 📨

---

## 根命令

当前 `nomi --help` 可见的根命令主要有：

- `nomi onboard`
- `nomi instance`
- `nomi agent`
- `nomi channel`
- `nomi remote`
- `nomi status`

根入口定义在 [nomi/cli/app.py](../nomi/cli/app.py#L25-L87)。

### 根级选项

当前 root callback 里固定有这些全局选项：

- `--version`
- `--install-completion`
- `--show-completion`

对应代码：[nomi/cli/app.py](../nomi/cli/app.py#L48-L87)

---

## `nomi agent`

### 两种运行模式

`nomi agent` 当前有两种形态：

1. 交互模式
2. 单次消息模式

命令定义在 [nomi/cli/commands/agent.py](../nomi/cli/commands/agent.py#L33-L128)。

### 交互模式

```bash
nomi agent
```

特点：

- 进入 prompt_toolkit 交互循环
- runtime 在后台启动
- 输入一条消息，发布到 bus
- agent 输出流式回显到终端

实际循环在 [nomi/cli/interactive.py](../nomi/cli/interactive.py#L54-L313)。

### 单次模式

```bash
nomi agent -m "帮我看一下这个目录"
```

特点：

- 调用 `runtime.run_once()`
- 一次请求，一次回复
- 适合脚本或快速测试

对应逻辑在 [nomi/cli/commands/agent.py](../nomi/cli/commands/agent.py#L83-L110)。

### 常用参数

| 参数 | 说明 |
|---|---|
| `-m, --message` | 单次发送的消息 |
| `-s, --session` | 会话 key，默认 `cli:direct` |
| `-w, --workspace` | 覆盖工作区路径 |
| `-c, --config` | 覆盖配置文件路径 |
| `--instance` | 按实例名解析当前实例 |
| `--instance-root` | 直接指定实例 root |
| `--markdown / --no-markdown` | 是否按 Markdown 渲染 |
| `--logs / --no-logs` | 是否显示 runtime 日志 |

---

## 交互循环

交互循环的真实行为不是“直接调用 agent”，而是通过消息总线工作：

```text
read_interactive_input_async()
  ↓
publish_inbound(InboundMessage)
  ↓
bus.consume_outbound()
  ↓
renderer 输出
```

关键逻辑：

- 启动提示与 signal handler：[nomi/cli/interactive.py](../nomi/cli/interactive.py#L37-L53)
- 主循环：[nomi/cli/interactive.py](../nomi/cli/interactive.py#L54-L313)
- outbound 消费：[nomi/cli/interactive.py](../nomi/cli/interactive.py#L132-L194)

---

## 快捷键与退出行为

### `Esc`

当前语义：

- 只在“当前有活跃回复”时生效
- 触发 `interrupt_session()`
- 中断当前这轮回复，而不是退出整个进程

交互侧接线见 [nomi/cli/interactive.py](../nomi/cli/interactive.py#L232-L280)。

### `Ctrl+C`

当前语义：

- 退出整个交互进程

对应逻辑：

- signal handler：[nomi/cli/interactive.py](../nomi/cli/interactive.py#L37-L53)
- 主循环兜底：[nomi/cli/interactive.py](../nomi/cli/interactive.py#L296-L303)

### 退出命令

这些文本会退出交互：

- `exit`
- `quit`
- `/exit`
- `/quit`
- `:q`

见 [nomi/cli/interactive.py](../nomi/cli/interactive.py#L29-L35)。

---

## Slash 命令

CLI 里的 slash 命令不是交给模型，而是在进入模型前就被路由掉。

当前内置命令定义在 [nomi/command/handlers/builtin.py](../nomi/command/handlers/builtin.py#L17-L72)。

命令列表：

| 命令 | 说明 |
|---|---|
| `/new` | 开始新会话 |
| `/restart` | 原地重启进程 |
| `/status` | 查看当前会话状态 |
| `/dream` | 手动触发 Dream |
| `/dream-log` | 查看 Dream 历史 |
| `/dream-restore` | 回滚 Dream 版本 |
| `/user-review` | 查看待确认画像候选 |
| `/user-apply <id>` | 确认画像写入 `USER.md` |
| `/user-reject <id>` | 拒绝画像候选 |
| `/user-show` | 查看当前 `USER.md` |
| `/skill list` | 查看全局 skills |
| `/skill install <source>` | 安装 skill |
| `/skill uninstall <name>` | 卸载 skill |
| `/help` | 查看命令帮助 |

---

## `nomi channel`

`channel` 是当前唯一的外部 channel CLI 入口。

子命令定义在 [nomi/cli/commands/channel.py](../nomi/cli/commands/channel.py#L24-L103)：

| 命令 | 说明 |
|---|---|
| `nomi channel enable weixin` | 启用微信 adapter 配置 |
| `nomi channel disable` | 禁用当前 channel adapter 配置 |
| `nomi channel login` | 当前 active channel 登录 |
| `nomi channel status` | 查看 channel adapter 状态 |

`enable / disable / login / status` 现在都支持：

- `--instance`
- `--instance-root`
- `--config`

channel 不再负责启动进程。配置变化通过 `nomi instance restart` 应用。

## `nomi remote`

`remote` 是桌面壳 HTTP API + SSE adapter 的配置入口。

当前子命令：

- `nomi remote enable`
- `nomi remote disable`
- `nomi remote token`
- `nomi remote rotate-token`
- `nomi remote status`

remote 不再负责启动进程。真正的监听由 `nomi instance start/restart` 挂载。

---

## `nomi instance`

`instance` 是真正的实例管理入口。

当前子命令：

- `nomi instance list`
- `nomi instance create <name>`
- `nomi instance inspect <name>`
- `nomi instance remove <name>`
- `nomi instance run [name]`
- `nomi instance start [name]`
- `nomi instance stop [name]`
- `nomi instance restart [name]`
- `nomi instance log [name]`
- `nomi instance status [name]`
- `nomi instance services`

实现见 [nomi/cli/commands/instance.py](../nomi/cli/commands/instance.py#L1-L96)。

---

## `nomi onboard`

`onboard` 现在是实例初始化入口。

当前行为：

- 默认初始化 `default -> ~/.nomi`
- 显式 `--instance` 或 `--instance-root` 时初始化对应实例
- 配置不存在时创建实例级配置
- 配置存在时允许覆盖或刷新
- `--wizard` 时进入交互式向导
- 最后同步该实例下 workspace 模板

对应代码：[nomi/cli/commands/onboard.py](../nomi/cli/commands/onboard.py#L16-L125)

---

## `nomi status`

`status` 是一个独立的 CLI 命令，不是 slash 命令。

它会读取：

- 当前 instance
- 当前 config
- 当前 workspace
- 当前默认 provider/model/timezone
- 统一 runtime service 运行状态
- remote adapter 状态
- channel adapter 状态

命令入口：[nomi/cli/commands/status.py](../nomi/cli/commands/status.py#L13-L37)  
状态聚合：[nomi/cli/support/status.py](../nomi/cli/support/status.py#L29-L75)

---

## CLI 和 runtime 的边界

当前代码里这条边界很重要：

- CLI 负责参数解析、交互循环、渲染
- runtime 负责装配和生命周期

也就是说：

- `nomi/cli/commands/agent.py` 不自己 new provider
- `nomi/runtime/app.py` 不负责 prompt_toolkit 交互

这条边界是现在整套结构能维持清晰的前提之一。
