# Nomi 单一实例统一 Runtime 计划

> 本文件记录当前 runtime 统一重构状态。后续 instance/runtime/task/channel/remote 相关实现、测试、文档与验收均以这里为准。

## 1. 目标语义

- `instance` 是唯一运行主体。
- 一个 instance root 下只允许一个活跃 runtime 进程。
- `remote` 和 `channel` 是挂载在该 runtime 上的 adapter，不再是独立 service。
- `task / session / provider / memory / bus` 都归唯一 `NomiRuntime + AgentLoop` 持有。
- 启动 instance 时，按配置挂载已启用 adapter。
- 停止 instance 时，停止全部 adapter 和 runtime。
- channel 启停是配置语义：`channel enable/disable` 后通过 `instance restart` 生效。

## 2. 当前完成状态

已落地：

- 新增实例级 runtime service：
  - `runtime-service.pid`
  - `runtime-service.json`
  - `runtime-service.log`
- `nomi instance run/start/stop/restart/log/status/services` 已成为唯一进程管理入口。
- `nomi remote` 已退回配置与凭证入口：
  - `enable`
  - `disable`
  - `token`
  - `rotate-token`
  - `status`
- `nomi channel` 已退回配置、登录与状态入口：
  - `enable`
  - `disable`
  - `login`
  - `status`
- `SingleChannelRunner` 已从独占 `consume_outbound()` 改为 `subscribe_outbound()`。
- `remote` 和 `channel` 现在可以并列订阅同一个 runtime bus。
- `AgentLoop` 支持同一 runtime 内多个 reminder consumer。
- task 全局提醒目标已改为读取 `runtime-service.json`。
- `status` 和 `instance services` 已以统一 runtime 状态为准。
- 启动统一 runtime 时会拒绝旧 remote/channel 独立 service 仍在运行的状态。

## 3. 当前固定命令面

进程管理只走：

- `nomi instance run [name]`
- `nomi instance start [name]`
- `nomi instance stop [name]`
- `nomi instance restart [name]`
- `nomi instance log [name]`
- `nomi instance status [name]`
- `nomi instance services`

remote 只做配置与凭证：

- `nomi remote enable`
- `nomi remote disable`
- `nomi remote token`
- `nomi remote rotate-token`
- `nomi remote status`

channel 只做配置、登录与状态：

- `nomi channel enable weixin`
- `nomi channel disable`
- `nomi channel login`
- `nomi channel status`

明确不再保留：

- `nomi remote run/start/stop/restart/log`
- `nomi channel run/start/stop/restart/log`

## 4. 仍保留的边界

- 第一版不做 adapter 热插拔，配置变化通过 `nomi instance restart` 生效。
- 第一版不改 `nomi-protocol`。
- 第一版仍只支持一个 active channel。
- 第一版不做自动端口分配。
- 旧 remote/channel service state 不做迁移，只检测并拒绝与统一 runtime 同时运行。

## 5. 验收状态

已跑过并通过：

- `uv run python -m pytest tests/cli/test_commands.py tests/channels/test_service.py tests/runtime/test_service_runner.py -q`
- `uv run python -m pytest tests/remote/test_server.py tests/tools/test_task_tool.py tests/cron/test_cron_service.py tests/bus/test_queue.py -q`
- `uv run python -m compileall nomi tests -q`

待做真实 smoke：

1. `nomi instance restart default`
2. `nomi instance status default`
3. desktop 连接 remote
4. 微信 channel 收发
5. desktop 创建 1 分钟提醒
6. 到点后 desktop 和微信都收到
7. `nomi instance services` 只显示一个 runtime pid
