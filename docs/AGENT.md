# 🤖 Agent

`AgentLoop` 是 Nomi 主链路的执行中枢。

你可以把它理解成“总调度台” 🎛️

它不是什么都自己干，而是把几类 owner 组装起来、协调起来：

- context
- session
- memory
- tools
- runner
- cron
- command
- loop runtime state / control

---

## AgentLoop 的位置

主类在 [nomi/agent/loop.py](../nomi/agent/loop.py#L87-L360)。

初始化时会装配：

- `MemoryStore`
- `SkillRegistry`
- `ContextBuilder`
- `SessionManager`
- `ToolRegistry`
- `AgentRunner`
- `CronService`
- `Consolidator`
- `AutoCompact`
- `Dream`
- `UserProfileService`
- `CommandRouter`
- `TurnProcessor`
- `DispatchRuntime`
- `BackgroundRuntime`

见 [nomi/agent/loop.py](../nomi/agent/loop.py#L145-L213)。

---

## 主链路怎么跑

### 直连调用

当 CLI 用 `runtime.run_once()` 或 channel 收到一条消息后，最终都会进入：

```text
AgentLoop.process_direct(...)
  ↓
TurnProcessor.process_message_result(...)
```

虽然 `process_direct()` 代码不在这里展开，但单轮核心 owner 是 [nomi/agent/execution/processor.py](../nomi/agent/execution/processor.py#L261-L420)。

### 总线消费

当 runtime 在后台启动时，`AgentLoop` 会持续消费 `bus.inbound`，然后把结果发回 `bus.outbound`。

与分发、pending queue、并发门控相关的逻辑主要在：

- `loop_runtime/dispatch.py`
- `loop_runtime/control.py`
- `loop_runtime/state.py`

---

## 单轮执行流程

一条正常消息的大致流程是：

```text
1. 取出 session
2. 恢复 runtime checkpoint
3. 检查 quick action（用户画像确认）
4. 检查 slash 命令
5. 做 token consolidation
6. 组装上下文消息
7. 调 AgentRunner 跑 tool loop
8. 保存本轮消息
9. 触发画像候选抽取
10. 生成最终 OutboundMessage
```

关键实现：

- 入口：[nomi/agent/execution/processor.py](../nomi/agent/execution/processor.py#L261-L420)
- tool loop：[nomi/agent/execution/processor.py](../nomi/agent/execution/processor.py#L168-L259)
- 会话写回：[nomi/agent/execution/processor.py](../nomi/agent/execution/processor.py#L520-L560)

---

## 当前 `AgentLoop` 里的三类运行态 owner

### `TurnProcessor`

负责：

- 单轮消息执行
- tool loop 调用
- checkpoint 恢复与清理
- 最终消息写回
- 用户画像候选抽取提醒

定义在 [nomi/agent/execution/processor.py](../nomi/agent/execution/processor.py#L154-L560)。

### `DispatchRuntime`

负责：

- bus 入站消费
- 同会话串行化
- pending queue
- 并发 gate

### `BackgroundRuntime`

负责：

- cron job 触发执行
- Dream 后台任务
- MCP 生命周期

这两部分由 `AgentLoop` 在初始化阶段装配：

- [nomi/agent/loop.py](../nomi/agent/loop.py#L209-L213)

---

## 工具调用

`AgentLoop` 自己不执行工具，而是：

1. 通过 `register_default_tools()` 注册默认工具
2. 把工具注册表传给 `AgentRunner`
3. 在工具调用前后通过 hook 处理进度、stream、tool hint

关键代码：

- 工具注册：[nomi/agent/loop.py](../nomi/agent/loop.py#L193-L205)
- Loop hook：[nomi/agent/execution/processor.py](../nomi/agent/execution/processor.py#L48-L152)

---

## 中断

当前中断入口是：

```python
AgentLoop.interrupt_session(session_key, reason="user_interrupt")
```

对应代码：[nomi/agent/loop.py](../nomi/agent/loop.py#L218-L237)

交互里按 `Esc` 后，最终也是走这条入口。

中断状态保存在 loop runtime state 里，不再用一套旧镜像字段单独维护。

---

## 会话与 unified session

`AgentLoop` 支持两种会话模式：

- 普通按 `channel:chat_id` 分 session
- `unified_session=True` 时，统一收敛到 `unified:default`

对应常量和逻辑：

- `UNIFIED_SESSION_KEY`：[nomi/agent/loop.py](../nomi/agent/loop.py#L44-L45)
- session key 归一化：[nomi/agent/loop.py](../nomi/agent/loop.py#L238-L242)
- effective key：[nomi/agent/loop.py](../nomi/agent/loop.py#L356-L360)

---

## 状态快照

`/status` 和 runtime status 都依赖会话级状态快照。

快照内容包括：

- 当前版本
- 当前模型
- 启动时间
- 最近一次 token usage
- 上下文窗口大小
- 当前会话消息数
- 当前上下文 token 估算
- 搜索额度说明（如果可取）

构造逻辑在 [nomi/agent/loop.py](../nomi/agent/loop.py#L254-L288)。

---

## Dream 与用户画像

`AgentLoop` 当前主链路已经接入两条“对话后异步演化”的记忆能力：

### Dream

- 负责长期记忆整理
- 可手动触发 `/dream`
- 也可后台触发

### User Profile

- 对话后尝试抽取画像候选
- 写入 `user_profile_candidates.json`
- 提醒用户确认
- 通过自然语言“记住”或 `/user-apply` 写回 `USER.md`

这两条都已经不是“计划中的能力”，而是当前主链路的一部分。

---

## 当前外部稳定入口

从 runtime / CLI / channel 角度看，`AgentLoop` 对外稳定入口主要就是这些：

- `interrupt_session()`
- `reset_session()`
- `build_status_snapshot()`
- `trigger_dream_background()`
- `list_cron_jobs()`
- `remove_cron_job()`

这些入口对应的职责边界已经比较稳定，后续重构最好不要再把更多 UI 或协议细节塞回 `AgentLoop` 本体。
