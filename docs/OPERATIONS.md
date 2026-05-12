# Nomi 操作手册

这份手册只覆盖当前已经落地的用户操作：初始化实例、配置模型、启动实例 runtime、启用 remote、启用微信 channel，以及创建和管理新实例。

当前最重要的运行模型是：

- `instance` 是后台运行主体。
- 一个实例 root 只允许一个后台 `runtime` 进程。
- `remote` 和 `channel` 都是挂在这个 runtime 上的 adapter。
- `remote/channel` 配置变化不会热加载，需要 `nomi instance restart` 生效。
- `nomi agent` 是终端交互入口，不是后台 service 管理入口。

相关实现入口：

- 实例命令：[../nomi/cli/commands/instance.py#L37-L260](../nomi/cli/commands/instance.py#L37-L260)
- remote 命令：[../nomi/cli/commands/remote.py#L15-L142](../nomi/cli/commands/remote.py#L15-L142)
- channel 命令：[../nomi/cli/commands/channel.py#L21-L120](../nomi/cli/commands/channel.py#L21-L120)
- onboard 命令：[../nomi/cli/commands/onboard.py#L18-L143](../nomi/cli/commands/onboard.py#L18-L143)
- runtime service：[../nomi/runtime/service/runner.py#L74-L220](../nomi/runtime/service/runner.py#L74-L220)

---

## 1. 安装和升级本地命令

在仓库目录安装依赖：

```bash
cd /Users/lixinlv/Doing/nomi-core
uv sync
```

如果要跑测试或开发：

```bash
uv sync --extra dev
```

安装为全局 `nomi` 命令：

```bash
uv tool install -e /Users/lixinlv/Doing/nomi-core --force
nomi --version
```

每次本地代码更新后，如果你要用全局 `nomi` 命令验证，都需要重新执行：

```bash
uv tool install -e /Users/lixinlv/Doing/nomi-core --force
```

---

## 2. 默认实例初始化

默认实例名固定是 `default`，默认 root 固定是：

```text
~/.nomi
```

初始化默认实例：

```bash
nomi onboard
```

初始化后会生成：

```text
~/.nomi/config.json
~/.nomi/workspace/
~/.nomi/logs/
~/.nomi/skills/
~/.nomi/history/
~/.nomi/media/
~/.nomi/sessions/
```

实例 root 和目录规则见 [../nomi/config/instance.py#L13-L25](../nomi/config/instance.py#L13-L25) 和 [../nomi/config/instance.py#L193-L199](../nomi/config/instance.py#L193-L199)。

如果要用交互式向导：

```bash
nomi onboard --wizard
```

如果要显式初始化默认实例：

```bash
nomi onboard --instance default
```

---

## 3. 配置模型

默认配置文件是：

```text
~/.nomi/config.json
```

最小需要配置：

```json
{
  "agents": {
    "defaults": {
      "provider": "deepseek",
      "model": "deepseek-chat",
      "timezone": "Asia/Shanghai"
    }
  },
  "providers": {
    "deepseek": {
      "apiKey": "你的 API Key"
    }
  }
}
```

当前默认时区是 `Asia/Shanghai`，定义在 [../nomi/config/schema/agent.py#L20-L38](../nomi/config/schema/agent.py#L20-L38)。

配置文件使用 camelCase，例如：

- Python 字段 `api_key` 在配置文件里是 `apiKey`
- Python 字段 `auth_token` 在配置文件里是 `authToken`

配置别名规则见 [../nomi/config/schema/root.py#L36-L42](../nomi/config/schema/root.py#L36-L42)。

---

## 4. 启动和管理默认实例 runtime

后台启动默认实例：

```bash
nomi instance start
```

前台运行默认实例，适合临时调试：

```bash
nomi instance run
```

重启默认实例：

```bash
nomi instance restart
```

停止默认实例：

```bash
nomi instance stop
```

查看默认实例状态：

```bash
nomi instance status
```

查看所有实例服务状态：

```bash
nomi instance services
```

跟随默认实例日志：

```bash
nomi instance log
```

默认实例日志路径：

```text
~/.nomi/logs/runtime-service.log
```

runtime 状态文件：

```text
~/.nomi/logs/runtime-service.pid
~/.nomi/logs/runtime-service.json
~/.nomi/logs/runtime-service.log
```

状态文件定义见 [../nomi/runtime/service/state.py#L19-L68](../nomi/runtime/service/state.py#L19-L68)。

---

## 5. 启用 remote

remote 是给 desktop 或其他远程客户端连接的 WebSocket adapter。

启用默认 remote 配置：

```bash
nomi remote enable
```

指定监听地址和端口：

```bash
nomi remote enable --host 127.0.0.1 --port 8765
```

配置写入后必须重启实例 runtime：

```bash
nomi instance restart
```

查看 remote 状态：

```bash
nomi remote status
```

查看当前 token：

```bash
nomi remote token
```

轮换 token：

```bash
nomi remote rotate-token
nomi instance restart
```

禁用 remote：

```bash
nomi remote disable
nomi instance restart
```

默认 remote 配置定义在 [../nomi/config/schema/remote.py#L8-L14](../nomi/config/schema/remote.py#L8-L14)。

默认 WebSocket 地址：

```text
ws://127.0.0.1:8765/ws
```

浏览器或 desktop smoke 可以用 query token：

```text
ws://127.0.0.1:8765/ws?token=<token>
```

非浏览器客户端优先使用 Bearer Token：

```text
Authorization: Bearer <token>
```

---

## 6. 启用微信 channel

当前唯一可用的外部 channel kind 是 `weixin`。

启用微信 adapter 配置：

```bash
nomi channel enable weixin
```

首次使用前登录微信：

```bash
nomi channel login
```

如果要强制重新登录：

```bash
nomi channel login --force
```

登录完成后启动或重启实例 runtime：

```bash
nomi instance restart
```

查看 channel 状态：

```bash
nomi channel status
```

禁用 channel：

```bash
nomi channel disable
nomi instance restart
```

查看微信运行日志：

```bash
nomi instance log
```

微信配置定义见 [../nomi/config/schema/channel.py#L12-L36](../nomi/config/schema/channel.py#L12-L36)。

注意：

- `nomi channel enable` 必须带 kind，也就是 `nomi channel enable weixin`。
- `channel enable/disable` 只修改配置，不直接启停进程。
- 实例运行时如果没有微信登录态，会跳过 channel adapter，并在状态里显示未运行。

---

## 7. 默认实例完整启动流程

从干净状态跑通默认实例，可以按这个顺序：

```bash
nomi onboard
```

编辑配置：

```bash
$EDITOR ~/.nomi/config.json
```

启用 remote：

```bash
nomi remote enable --host 127.0.0.1 --port 8765
nomi remote token
```

启用并登录微信：

```bash
nomi channel enable weixin
nomi channel login
```

启动实例 runtime：

```bash
nomi instance start
```

确认状态：

```bash
nomi instance status
nomi remote status
nomi channel status
nomi instance services
```

看日志：

```bash
nomi instance log
```

---

## 8. 创建和启动新实例

创建命名实例：

```bash
nomi instance create xmy
```

初始化该实例：

```bash
nomi onboard --instance xmy
```

编辑该实例配置：

```bash
$EDITOR ~/.nomi/instances/xmy/config.json
```

启用该实例的 remote：

```bash
nomi remote enable --instance xmy --host 127.0.0.1 --port 8766
nomi remote token --instance xmy
```

启用并登录该实例的微信：

```bash
nomi channel enable weixin --instance xmy
nomi channel login --instance xmy
```

启动该实例：

```bash
nomi instance start xmy
```

查看该实例状态：

```bash
nomi instance status xmy
nomi remote status --instance xmy
nomi channel status --instance xmy
```

跟随该实例日志：

```bash
nomi instance log xmy
```

停止该实例：

```bash
nomi instance stop xmy
```

删除该实例：

```bash
nomi instance remove xmy
```

`default` 实例不允许删除，规则见 [../nomi/config/instance.py#L137-L147](../nomi/config/instance.py#L137-L147)。

---

## 9. 使用自定义 instance root

如果不想注册实例名，可以直接指定 root：

```bash
nomi onboard --instance-root /tmp/nomi-demo
nomi remote enable --instance-root /tmp/nomi-demo --host 127.0.0.1 --port 8770
nomi channel enable weixin --instance-root /tmp/nomi-demo
nomi channel login --instance-root /tmp/nomi-demo
nomi instance start --instance-root /tmp/nomi-demo
```

查看状态：

```bash
nomi instance status --instance-root /tmp/nomi-demo
nomi instance log --instance-root /tmp/nomi-demo
```

实例解析优先级固定为：

```text
--instance-root > --instance > --config > default
```

解析规则见 [../nomi/config/instance.py#L174-L190](../nomi/config/instance.py#L174-L190)。

---

## 10. 常用命令速查

实例：

```bash
nomi instance list
nomi instance create <name>
nomi instance inspect <name>
nomi instance remove <name>
nomi instance start [name]
nomi instance run [name]
nomi instance stop [name]
nomi instance restart [name]
nomi instance status [name]
nomi instance services
nomi instance log [name]
```

remote：

```bash
nomi remote enable [--host HOST] [--port PORT]
nomi remote disable
nomi remote token
nomi remote rotate-token
nomi remote status
```

channel：

```bash
nomi channel enable weixin
nomi channel disable
nomi channel login [--force]
nomi channel status
```

终端交互：

```bash
nomi
nomi agent
nomi agent -m "你好"
nomi status
```

所有实例级命令都可以带：

```bash
--instance <name>
--instance-root <path>
--config <path>
```

---

## 11. 常见问题

### 改了 remote host/port，为什么还是旧地址？

`nomi remote enable --host ... --port ...` 只写配置。运行中的 runtime 不会热加载，需要执行：

```bash
nomi instance restart
```

### `nomi channel enable` 报缺少参数怎么办？

当前必须指定 channel kind：

```bash
nomi channel enable weixin
```

### 微信登录了但 channel 没跑起来怎么办？

先看配置和状态：

```bash
nomi channel status
nomi instance status
```

再看日志：

```bash
nomi instance log
```

如果 `logged_in: no`，重新登录：

```bash
nomi channel login --force
nomi instance restart
```

### remote 连接不上怎么办？

按顺序检查：

```bash
nomi remote status
nomi instance status
nomi remote token
nomi instance log
```

确认端口监听：

```bash
lsof -iTCP:8765 -sTCP:LISTEN -n -P
```

如果改过端口，把 `8765` 换成配置里的端口。

### 多实例能同时启动吗？

可以。每个实例有自己的 root、配置、日志、session 和 runtime pid。

但端口不会自动分配，所以多个实例同时启用 remote 时，必须手动配置不同端口：

```bash
nomi remote enable --instance default --port 8765
nomi remote enable --instance xmy --port 8766
```

然后分别启动：

```bash
nomi instance start default
nomi instance start xmy
```

### 怎么确认现在只有一个统一 runtime？

看实例服务汇总：

```bash
nomi instance services
```

单个实例应该只有一个 `runtime` pid。remote 和 channel 的 running 状态都挂在这一个实例 runtime 下。
