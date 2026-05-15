# 🛠️ 操作手册

这份手册讲 Nomi 当前真实可用的日常操作：初始化、配置模型、启动实例、连接 desktop、启用微信、创建新实例、查看日志和排障。

## ✅ 当前运行模型

先记住这几条：

- `instance` 是后台运行主体。
- 一个实例 root 只运行一个 runtime。
- `remote` 和 `channel` 都挂在这个 runtime 上。
- `remote/channel` 配置变更需要 `nomi instance restart`。
- `nomi agent` 是终端对话入口，不是后台 service 管理入口。

## 📦 安装本地命令

在仓库目录安装依赖：

```bash
cd /Users/lixinlv/Doing/nomi-core
uv sync
```

安装为全局 `nomi` 命令：

```bash
uv tool install -e /Users/lixinlv/Doing/nomi-core --force
nomi --version
```

本地代码更新后，如果要用全局 `nomi` 命令验证，需要重新安装：

```bash
uv tool install -e /Users/lixinlv/Doing/nomi-core --force
```

## 🚀 初始化默认实例

默认实例 root 是：

```text
~/.nomi
```

初始化：

```bash
nomi onboard
```

初始化后通常会得到：

```text
~/.nomi/
├── config.json
├── workspace/
├── sessions/
├── skills/
└── logs/
```

`TOOLS.md` 不再生成到 workspace，它由 core 内置模板注入。

## 🤖 配置模型

配置文件是：

```text
~/.nomi/config.json
```

常见配置目标：

- active provider
- model
- API key
- remote host / port / token
- channel kind
- instance key

配置改完后，已经运行的后台实例需要重启：

```bash
nomi instance restart
```

## 🌐 启用 Desktop Remote

启用 remote：

```bash
nomi remote enable --host 127.0.0.1 --port 8765
nomi remote token
nomi instance restart
```

desktop 连接地址通常是：

```text
http://127.0.0.1:8765
```

鉴权使用 remote token。

查看状态：

```bash
nomi remote status
nomi instance status
```

## 💬 启用微信 Channel

启用微信：

```bash
nomi channel enable weixin
nomi channel login
nomi instance restart
```

查看状态：

```bash
nomi channel status
nomi instance status
```

如果微信未登录，实例 runtime 仍然可以启动，但 channel adapter 不会运行。

## ⚙️ 启动和停止实例

后台启动：

```bash
nomi instance start
```

前台运行：

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

查看日志：

```bash
nomi instance log
```

## 🧩 创建第二个实例

创建命名实例：

```bash
nomi instance create xmy
```

启动命名实例：

```bash
nomi instance start xmy
```

配置第二个实例的 remote 端口时，需要避免和默认实例冲突：

```bash
nomi remote enable --instance xmy --host 127.0.0.1 --port 8766
nomi instance restart xmy
```

## 🤝 两个实例加好友

A 生成邀请码：

```bash
nomi instance invite-code
```

B 使用邀请码申请：

```bash
nomi instance invite --from-code "nomi://instance-invite?..."
```

A 接受：

```bash
nomi instance accept xmy --permission chat
```

发送消息：

```bash
nomi instance send xmy "你现在方便吗？"
```

## ⏰ 创建自动任务

用户可以直接在任意入口说：

```text
10 分钟后提醒我喝水。
每天早上 9 点提醒我量体重。
```

任务默认是全局提醒，会投递给当前实例里正在运行且可接收提醒的入口。

## 🧪 快速检查

常用检查命令：

```bash
nomi --help
nomi instance services
nomi instance status
nomi remote status
nomi channel status
```

如果 desktop 连不上，优先看：

- 实例是否运行。
- remote 是否 enabled。
- remote host/port 是否和 desktop 配置一致。
- token 是否一致。
- 端口是否冲突。

## 🧱 注意事项

- 不要同时用旧 remote/channel service 思路排障。
- 不要手动删除服务器上的整套 `~/.nomi`，除非明确要重置运行态。
- 清本地测试实例时，保留必要的 `config.json` 和微信登录态。
- 自动任务不会在实例停止时独立执行。
- 修改 provider、remote、channel 配置后，重启实例最稳。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/cli/commands/onboard.py](./nomi/cli/commands/onboard.py#L18-L143) | 初始化命令 |
| [nomi/cli/commands/instance.py](./nomi/cli/commands/instance.py#L37-L497) | 实例管理命令 |
| [nomi/cli/commands/remote.py](./nomi/cli/commands/remote.py#L15-L142) | remote 配置命令 |
| [nomi/cli/commands/channel.py](./nomi/cli/commands/channel.py#L21-L120) | channel 配置和登录命令 |
| [nomi/runtime/service/runner.py](./nomi/runtime/service/runner.py#L74-L220) | runtime service 启停 |
| [nomi/config/instance.py](./nomi/config/instance.py#L13-L258) | 实例 root 解析 |
| [nomi/config/loader.py](./nomi/config/loader.py#L1-L211) | 配置加载和保存 |
