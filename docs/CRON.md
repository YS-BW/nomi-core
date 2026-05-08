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

当前 cron 数据默认保存在：

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

- start：[nomi/cron/service.py](../nomi/cron/service.py#L188-L197)
- run_due_jobs：[nomi/cron/service.py](../nomi/cron/service.py#L209-L219)
- execute_job：[nomi/cron/service.py](../nomi/cron/service.py#L221-L260)

---

## 和 Agent 的接线

`AgentLoop` 初始化时会创建 `CronService`，并把：

```python
self.cron_service.on_job = self._run_cron_job
```

接上去。

代码位置：

- [nomi/agent/loop.py](../nomi/agent/loop.py#L159-L163)
- [nomi/agent/loop.py](../nomi/agent/loop.py#L302-L305)

也就是说，cron 到点后最终还是回到 Agent 主链路执行。

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

当前 cron 的产品边界一定要记住：

- 它是应用内调度
- 不是系统后台常驻服务
- 如果 `nomi agent` 或 channel runtime 不在跑，就不会触发

所以它适合：

- 提醒
- 周期性 agent 行为
- 会回到聊天上下文里的触发任务

但不适合被文档写成“真正的系统级定时器”。
