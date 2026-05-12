# Nomi 任务系统重构计划

> 本文件替换旧版 `PLAN.md`，后续任务系统相关实现、测试、文档与验收均以这里为准。

## 1. 计划目标

用户要的最终产品语义固定如下：

- 任务可以从 `CLI` 创建。
- 任务也可以从 `desktop/remote` 创建。
- 创建入口和最终投递出口解耦。
- 最终提醒走实例级全局投递：同一实例里所有已启动入口各自收到一份，不在当前公开接口里暴露额外 target 字段。
- 同一个 `instance` 下，任务必须由统一调度器可靠执行。

本计划的实施顺序固定为：

1. 先止血，修复 task/job 脱钩与无自愈。
2. 再把任务调度从“每个 runtime 各管一份”收口成实例级单 scheduler owner。
3. 再评估是否要继续上升到共享 runtime / instance core service。

## 2. 当前代码事实

当前任务系统已经确认的结构性问题：

- `tasks.json` 保存任务定义；
- `cron/jobs.json` 保存底层调度触发器；
- `remote` 和 `channel` 各自启动自己的 `runtime / AgentLoop / TaskRunner / CronService`；
- 多个 runtime 读写同一个 instance root 时，之前没有 reconcile 和单 owner 机制；
- 任务创建入口默认绑定当前上下文；
- 当前公开接口不需要新增显式 `target_channel / target_chat_id` 参数，提醒改为走实例级全局投递。

## 3. 当前完成状态

### 3.1 已完成

- `tasks.json` 已收口为任务定义真源。
- runtime 启动时，任务层会从 `tasks.json` 自愈重建全部 `target_kind == "task"` 的 cron 触发器。
- `CronService` 已支持按 `target_kind` 原子替换一组派生 job，避免 task reconcile 时误伤非任务类 cron 记录。
- 同一实例下已经增加单 scheduler owner 机制：
  - 通过实例级锁文件保证同一实例只有一个 runtime 真正启动 cron 调度；
  - 其他 runtime 保持 follower 模式，只读写任务定义，不再直接启动自己的 task cron。
- scheduler owner 会在主循环 idle tick 中轮询 `tasks.json` 变化并重建 task cron；
  - 因此 follower runtime 新建或修改任务后，owner runtime 能自动接管新的派生调度状态。
- 任务结果不再只回创建端：
  - scheduler owner 会把任务最终结果写入实例级共享提醒队列；
  - `remote / channel / cli` 这些已启动入口会各自轮询消费属于自己的提醒副本；
  - 因此 desktop 创建的任务，到点后可以同时出现在 desktop、微信等当前已启动入口上。
- `prepared_delivery` 仍保持完整的 `prepare + deliver` 双阶段派生 job 语义。
- 核心测试已补齐并通过：
  - `tests/tools/test_task_tool.py`
  - `tests/cron/test_cron_service.py`
  - `tests/cli/test_runtime.py`
  - `tests/remote/test_server.py`

### 3.2 当前仍保留的限制

- 当前没有引入新的独立 scheduler service；单 owner 仍挂在现有 runtime 进程上。
- 当前没有改 `nomi-protocol`，也没有改 desktop wire shape。
- 当前全局提醒依赖“入口已启动且存在可投递会话”：
  - remote 侧会广播给当前所有已连接客户端；
  - channel 侧会投递到该渠道最近活跃的会话；
  - CLI 侧只会投递给当前正在运行的 `nomi agent`。

## 4. 固定设计结论

### 4.1 已经落地的设计

- **任务定义唯一真源 = `tasks.json`**
- `cron/jobs.json` 已降级为派生调度状态，不再和 `tasks.json` 并列当真源
- **同一实例只能有一个 task scheduler owner**
- `remote / channel / cli` 可以继续作为不同入口，但不再都持有 live task scheduler 真相
- **任务结果投递改为实例级 fanout，而不是单个 target_channel/chat_id 单播**

### 4.2 当前不做的事情

- 不做 protocol 私改
- 不让 desktop 侧补 core 语义
- 不开放新的 `target_channel / target_chat_id` 公共创建参数
- 不直接上共享大 runtime
- 不引入新的独立 instance core service 作为当前 P0

## 5. 下一阶段

下一阶段固定聚焦两件事：

1. 真实实例 smoke：
   - 同一实例起 `remote`
   - 同一实例起 `channel weixin`
   - 从 CLI 或 desktop 创建任务
   - 校验 owner runtime 能自动接管并在到点时把提醒 fanout 给所有已启动入口
2. 文档继续收口：
   - 明确 `tasks.json` 是真源
   - 明确 `cron/jobs.json` 是派生状态
   - 明确当前采用实例级单 scheduler owner，而不是共享 runtime

## 6. 完成定义

本计划中的一个阶段，只有同时满足下面四项才算完成：

1. 代码实现完成；
2. 对应测试已新增或更新，并且实际跑过；
3. `docs/` 中相关文档已更新；
4. 本文件已回写当前完成状态、剩余风险与下一阶段优先级。
