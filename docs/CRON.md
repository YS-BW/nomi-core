# ⏰ Cron

Nomi 当前的调度系统是应用内 cron，不是系统级守护进程 ⏰

也就是说：

- 只有 agent/runtime 真正在跑时，任务才会触发 ▶️
- 它不依赖系统 `crontab`
- 它不依赖 `launchd`
- 它不依赖 Windows Task Scheduler

---

## 代码位置

- 类型定义：[nomi/cron/types.py](../nomi/cron/types.py)
- 调度服务：[nomi/cron/service.py](../nomi/cron/service.py#L25-L360)
- AI 工具：[nomi/agent/tools/cron.py](../nomi/agent/tools/cron.py)
- Agent 接线：[nomi/agent/loop.py](../nomi/agent/loop.py#L160-L163)

---

## 存储位置

当前 cron 派生调度状态默认保存在：

```text
~/.nomi/workspace/cron/jobs.json
```

路径定义见 [nomi/config/paths.py](../nomi/config/paths.py#L37-L44)。

---

## 调度模型

当前支持三种调度方式：

| 类型 | 说明 |
|---|---|
| `at` | 一次性在某个时间触发 |
| `every` | 固定间隔反复触发 |
| `cron` | 标准 cron 表达式 |

计算下一次触发时间的逻辑在 [nomi/cron/service.py](../nomi/cron/service.py#L81-L111)。

---

## 运行机制

当前 cron 运行机制大致是：

```text
TaskRunner.start_scheduler()
  ↓
抢实例级 scheduler owner 锁
  ↓
从 tasks.json 重建 task 类 jobs
  ↓
CronService.start()
  ↓
load jobs.json
  ↓
recompute next_run_at_ms
  ↓
arm timer
  ↓
到点后 run_due_jobs()
  ↓
_execute_job()
  ↓
回调 on_job(job)
```

关键代码：

- scheduler owner 启动：[nomi/tasks/runner.py](../nomi/tasks/runner.py#L245-L278)
- task reconcile：[nomi/tasks/runner.py](../nomi/tasks/runner.py#L221-L243)
- start：[nomi/cron/service.py](../nomi/cron/service.py#L207-L216)
- run_due_jobs：[nomi/cron/service.py](../nomi/cron/service.py#L209-L219)
- execute_job：[nomi/cron/service.py](../nomi/cron/service.py#L221-L260)

---

## 和 Agent 的接线

`AgentLoop` 初始化时会创建 `CronService + TaskRunner`，并把：

```python
self.cron_service.on_job = self._run_cron_job
```

接上去。

代码位置：

- [nomi/agent/loop.py](../nomi/agent/loop.py#L162-L167)
- [nomi/agent/loop_runtime/dispatch.py](../nomi/agent/loop_runtime/dispatch.py#L34-L47)

也就是说：

- task 定义真源在 `tasks.json`
- `CronService` 只负责派生调度状态和到点执行
- 到点后最终还是回到 Agent 主链路执行
- 任务结果会被写入实例级共享提醒队列，再由当前已启动入口各自消费一份

---

## 任务真源与单 owner

当前任务系统已经固定为：

- `tasks.json` 是任务定义真源
- `cron/jobs.json` 是派生调度状态
- 同一实例下只有一个 runtime 能成为 task scheduler owner

实现要点：

- owner runtime 通过实例级锁文件持有 scheduler 资格
- follower runtime 仍然可以创建、更新、删除任务定义
- owner runtime 会在主循环 idle tick 中轮询 `tasks.json` 变化，并重建 task 类 cron

这意味着同一实例下：

- 不会再让 `remote` 和 `channel` 同时各自启动自己的 task cron
- 新任务不依赖“必须在当前运行中的那一侧创建”才会被调度看到
- desktop/CLI 创建的任务也不再只回创建端，而是按实例级全局提醒语义 fanout 到所有已启动入口

---

## 全局提醒投递

当前任务结果默认不是简单的单个 `target_channel/chat_id` 单播，而是：

```text
task run completed
  ↓
写入实例级 reminders.json
  ↓
remote / channel / cli runtime 在 idle tick 中各自消费
  ↓
每个已启动入口收到一份提醒
```

如果任务显式设置了 `target_channels`，投递范围会被限制到指定入口：

- 不设置或设置为空：全局提醒，投递给当前实例里正在运行且可接收提醒的入口
- `["weixin"]`：只投递微信
- `["cli"]`：只投递 CLI
- `["remote"]`：只投递 remote / desktop
- 多个值：只投递这些入口

当前共享提醒记录默认保存在：

```text
~/.nomi/tasks/reminders.json
```

当前 fanout 语义固定为：

- `remote`：
  - 广播给当前所有已连接 desktop 客户端
- `channel`：
  - 投递给该渠道最近活跃的会话
- `cli`：
  - 只投递给当前正在运行的 `nomi agent`

这套语义的重点是：

- 创建入口和投递入口已经解耦
- 默认情况下，同一实例里只要某个入口当前正在运行，它就能各自收到同一条任务提醒
- 如果任务设置了 `target_channels`，则只向指定入口投递
- 当前公开 Agent 工具支持可选 `target_channels`
- remote 协议当前还没有 `target_channels` 字段；desktop 直接显式创建定向任务需要先走 `nomi-protocol` 变更流程

---

## AI 可以调用哪些 cron 工具

当前暴露给模型的工具固定是：

- `cron_create`
- `cron_list`
- `cron_delete`
- `cron_update`

工具注册在 [nomi/agent/tools/bootstrap.py](../nomi/agent/tools/bootstrap.py#L82-L84)。

当前没有：

- `/cron` slash 命令
- 旧的 `/task`

---

## 防重复与运行状态

`CronService` 里现在已经有一层“短窗口重复 job 复用”逻辑：

- 调度参数一样
- message 一样
- channel/chat_id 一样
- 创建时间相近

就直接复用已有 job，而不是新建一条。

逻辑在 [nomi/cron/service.py](../nomi/cron/service.py#L277-L324)。

### 运行历史

每个 job 还会保留有限 run history：

- 当前最多保留 20 条

见 [nomi/cron/service.py](../nomi/cron/service.py#L28-L30)。

---

## 重要限制

当前 cron / task 调度的产品边界一定要记住：

- 它是应用内调度
- 不是系统后台常驻服务
- 如果当前实例没有任何拿到 scheduler owner 的 runtime 在跑，就不会触发

所以它适合：

- 提醒
- 周期性 agent 行为
- 会回到聊天上下文里的触发任务

但它仍然不适合被文档写成“真正的系统级定时器”。
