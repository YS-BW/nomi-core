# 💻 CLI

CLI 是 Nomi 的本地命令入口。它既能直接和 Agent 对话，也能管理实例、remote、channel、provider 配置和运行状态。

当前最重要的理解是：

- `nomi agent` 是终端对话入口。
- `nomi instance` 是后台 runtime 管理入口。
- `nomi remote` 和 `nomi channel` 主要负责配置，不再单独启动 service。

## 🚀 常用命令

| 命令 | 用途 |
|---|---|
| `nomi onboard` | 初始化默认实例和配置 |
| `nomi agent` | 打开终端交互对话 |
| `nomi agent --message "..."` | 发一条单次消息 |
| `nomi instance start` | 后台启动默认实例 runtime |
| `nomi instance run` | 前台运行默认实例 runtime |
| `nomi instance stop` | 停止实例 runtime |
| `nomi instance restart` | 重启实例 runtime |
| `nomi instance status` | 查看实例状态 |
| `nomi instance services` | 查看所有实例服务状态 |
| `nomi remote enable` | 启用 remote adapter 配置 |
| `nomi channel enable weixin` | 启用微信 channel 配置 |

## 💬 终端对话

直接进入交互模式：

```bash
nomi agent
```

发送单次消息：

```bash
nomi agent --message "帮我总结一下今天的任务"
```

交互模式会启动本地 runtime，然后把用户输入送入 AgentLoop。模型回复会流式渲染到终端。

## 🧩 实例管理

默认实例名是 `default`，默认 root 是 `~/.nomi`。

常用命令：

```bash
nomi instance start
nomi instance status
nomi instance log
nomi instance restart
nomi instance stop
```

命名实例可以这样使用：

```bash
nomi instance create xmy
nomi instance start xmy
nomi instance status xmy
```

同一个实例 root 只允许一个后台 runtime 进程。remote 和 channel 都挂在这个 runtime 上。

## 🌐 Remote 配置

remote 给 desktop 使用。启用后，实例启动时会挂载 HTTP + SSE server。

```bash
nomi remote enable --host 127.0.0.1 --port 8765
nomi remote token
nomi instance restart
```

remote 配置变更不会热加载。修改 host、port 或 token 后，需要重启实例。

## 💬 微信 Channel 配置

当前唯一实际可用的 channel kind 是 `weixin`。

```bash
nomi channel enable weixin
nomi channel login
nomi instance restart
```

channel enable 只改配置。微信是否真正运行，取决于实例 runtime 是否启动，以及微信登录态是否可用。

## 🤝 Instance 关系命令

CLI 也可以管理两个 Nomi 实例之间的关系：

```bash
nomi instance key
nomi instance key 小美
nomi instance invite-code
nomi instance invite --from-code "nomi://instance-invite?..."
nomi instance accept xmy --permission chat
nomi instance reject xmy
nomi instance remove-relation xmy
nomi instance permission xmy task
nomi instance send xmy "你现在方便吗？"
```

这些命令和 Agent 工具使用的是同一套 instance relation 存储。

## 🧱 使用边界

- `nomi remote start/stop` 不再是主流程。
- `nomi channel start/stop` 不再是主流程。
- 配置类命令通常需要 `nomi instance restart` 才会影响正在运行的实例。
- `nomi agent` 是前台对话，不等于后台 service。
- 自动任务只有在实例 runtime 运行时才会触发。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/cli/app.py](../nomi/cli/app.py#L25-L87) | CLI 根命令注册 |
| [nomi/cli/commands/agent.py](../nomi/cli/commands/agent.py#L33-L139) | `nomi agent` |
| [nomi/cli/commands/instance.py](../nomi/cli/commands/instance.py#L37-L497) | `nomi instance` |
| [nomi/cli/commands/remote.py](../nomi/cli/commands/remote.py#L15-L142) | `nomi remote` |
| [nomi/cli/commands/channel.py](../nomi/cli/commands/channel.py#L21-L120) | `nomi channel` |
| [nomi/cli/commands/onboard.py](../nomi/cli/commands/onboard.py#L18-L143) | `nomi onboard` |
| [nomi/cli/commands/status.py](../nomi/cli/commands/status.py#L1-L42) | `nomi status` |
