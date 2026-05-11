# 🧩 Instance

`instance root` 现在是 Nomi 运行态的唯一事实源。

这套模型的目标很直接：

- 不再靠复制 `~/.nomi` 手工改配置
- 不再把 `--config` 当成主实例模型
- 所有运行态目录都从同一个 instance root 派生

---

## 固定语义

- 默认实例名固定是 `default`
- 默认实例 root 固定是 `~/.nomi`
- 命名实例默认注册在 `~/.nomi/instances.json`
- 命名实例默认 root 派生在 `~/.nomi/instances/<name>`
- `--instance-root` 优先级最高
- `--instance` 次之
- `--config` 只用来从 `dirname(config)` 反推 instance root
- 都不传时，一律落到 `default`

核心实现见 [nomi/config/instance.py](../nomi/config/instance.py#L13-L258)。

---

## 实例目录结构

每个实例 root 下统一派生这些目录：

```text
<instance-root>/
├── config.json
├── workspace/
├── logs/
├── skills/
├── history/
├── media/
└── sessions/
```

目录初始化和路径派生分别在：

- [nomi/config/instance.py](../nomi/config/instance.py#L193-L207)
- [nomi/config/paths.py](../nomi/config/paths.py#L15-L98)

这意味着：

- `sessions/` 不再挂在 `workspace/sessions`
- `skills/` 不再固定指向全局 `~/.nomi/skills`
- `history/` 和 `logs/` 也都是实例级

---

## CLI 入口

当前实例相关 CLI 有两层：

### 1. 通用实例参数

这些命令都支持：

- `--instance`
- `--instance-root`
- `--config`

已接入：

- `nomi onboard`
- `nomi agent`
- `nomi channel ...`
- `nomi remote ...`
- `nomi status`

共享解析入口在 [nomi/cli/support/config.py](../nomi/cli/support/config.py#L26-L109)。

### 2. `nomi instance` 命令组

当前包含：

- `nomi instance list`
- `nomi instance create <name>`
- `nomi instance inspect <name>`
- `nomi instance remove <name>`
- `nomi instance services`

命令定义在 [nomi/cli/commands/instance.py](../nomi/cli/commands/instance.py#L1-L96)。

其中：

- `default` 不允许删除
- `create` 会注册实例并创建标准目录
- `services` 会汇总所有实例的 channel/remote 服务状态

---

## 配置与路径

配置加载现在先解析实例上下文，再决定 `config.json`：

- `get_config_path()` 固定返回 `<instance-root>/config.json`
- `set_config_path()` 会把实例 root 绑定到配置文件所在目录
- `load_config()` 会把默认 workspace 重写到 `<instance-root>/workspace`

实现见 [nomi/config/loader.py](../nomi/config/loader.py#L1-L149)。

---

## Service 管理

channel / remote 的后台 service 现在按实例工作：

- `channel start/log/stop/restart --instance X`
- `remote start/log/stop/restart --instance X`

后台子进程命令会把实例参数继续透传下去，不再是全局语义。

相关代码：

- channel runner：[nomi/channel/service/runner.py](../nomi/channel/service/runner.py#L28-L190)
- remote runner：[nomi/remote/service/runner.py](../nomi/remote/service/runner.py#L28-L182)

状态展示与实例汇总在 [nomi/cli/support/status.py](../nomi/cli/support/status.py#L1-L136)。

---

## Session / Skills / History

这三类最容易漏掉的运行态现在都已经改成实例级：

- session：见 [nomi/agent/loop.py](../nomi/agent/loop.py#L145-L155)
- skills：见 [nomi/agent/skills/manager.py](../nomi/agent/skills/manager.py#L56-L63)
- CLI history：见 [nomi/cli/history.py](../nomi/cli/history.py#L108-L124)

微信登录时清理 session 的路径也已经改成实例级：

- [nomi/channel/adapters/weixin/channel.py](../nomi/channel/adapters/weixin/channel.py#L315-L333)

---

## 当前边界

这套 instance 模型当前明确不做两件事：

- 不做“全局当前实例切换”主语义
- 不做自动端口分配

命令主语义始终是“这次命令明确绑定到哪一个实例”。
