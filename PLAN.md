# Nomi 后续实现计划

> 这份文件是项目内部计划，不放进 `docs/`，也不当成用户文档。

## 1. 计划目标

Nomi 当前阶段的目标不变：

- 做成 nanobot 风格的终端 AI 助手
- 先把已有核心能力做清楚
- 不扩未来能力
- 不做兼容层
- 不做迁移脚本
- 不保留过渡实现

项目推进时，优先遵守这三条：

- 先相信代码事实，不按历史讨论想象当前实现
- 代码、测试、文档、计划必须保持一致
- 一次只推进一个模块，不跨方向混做

## 2. 当前代码事实

### 2.1 当前已经具备

- 终端主链路闭环
- 进程内 `runtime` 装配与生命周期管理
- 基础多轮对话
- 流式输出
- session 持久化
- workspace 模板初始化
- 全局 skills 扫描与 prompt 注入
- skill 的安装、卸载、列表管理
- 外部 skill root 可在安装时一次性导入到 `~/.nomi/skills`
- `cron` 调度的 CRUD 四工具协议
- 最小工具调用闭环
- DeepSeek 独立 provider backend
- DeepSeek tool-call transcript 的 `reasoning_content` 协议修复
- Qwen 独立 provider adapter
- Zhipu 独立 provider adapter
- Moonshot / Kimi 独立 provider adapter
- SiliconFlow 独立 provider adapter
- 单 runtime、单会话下的真实 interrupt
- `serve stdio` 第二入口
- `channels/` 适配层与 `weixin` 内置 channel
- `remote/` 远程 desktop shell 服务端 bridge
- `examples/remote-client/` 最小网页版协议验证器
- `nomi-desktop` 独立 Tauri 桌面仓
- runtime 级语音转写与语音合成 provider

### 2.2 当前还没有

- 系统级调度后端
- `heartbeat`
- 托盘、通知、拖拽吸附、角色动画和系统级 pet 能力

### 2.3 当前主链路

当前真实启动链路已经固定为：

```text
CLI
  ↓
runtime
  ↓
Bus
  ↓
AgentLoop
```

如果是 `serve stdio`，则链路是：

```text
stdin JSONL
  ↓
runtime.run_once()
  ↓
AgentLoop.process_direct()
```

如果是个人微信 channel，则链路是：

```text
Weixin HTTP long-poll
  ↓
WeixinChannel
  ↓
Bus
  ↓
AgentLoop
  ↓
Bus
  ↓
ChannelManager
  ↓
WeixinChannel
```

如果是 cron 触发，则链路是：

```text
workspace/cron/jobs.json
  ↓
CronService
  ↓
AgentLoop._run_cron_job()
  ↓
agent.process_direct(...)
```

如果是 remote desktop shell，则链路是：

```text
Desktop Shell
  ↓
Remote WebSocket
  ↓
RemoteServer
  ↓
Bus
  ↓
AgentLoop
  ↓
Bus outbound tap
  ↓
RemoteBridge
  ↓
Desktop Shell
```

### 2.4 当前结构边界

当前已经收口成下面这组 owner 分工：

```text
config        = 只保存配置事实
providers     = provider 元数据、解析、装配、model catalog
runtime       = 统一对外复用入口与生命周期
agent         = 执行循环、上下文装配、会话内控制
command       = slash 命令协议与 handler 组织
cron          = 调度模型、持久化、定时唤醒、执行状态
remote        = 远程 desktop shell 服务、WebSocket bridge、后台 service
agent/memory  = 记忆存储、压缩与 Dream
utils         = 低层通用小工具
```

### 2.5 当前必须固定下来的事实

- provider 解析入口在 `nomi/providers/resolution.py`
- provider 实例化入口在 `nomi/providers/factory.py`
- 模型目录 owner 在 `nomi/providers/model_catalog.py`
- `runtime` 是未来多入口唯一可复用底座
- 当前第二入口验证固定为 `serve stdio`
- `runtime` 对外不再暴露 `cancel_session_tasks()`，用户级中断入口固定为 `interrupt_session()`
- 当前 `serve channels` 也直接复用同一份 `NomiRuntime`
- 当前 `remote` 也直接复用同一份 `NomiRuntime`
- channel owner 固定在 `nomi/channels`
- 远程桌面壳 bridge owner 固定在 `nomi/remote`
- 当前内置 channel 固定为 `weixin`
- 当前最多只再考虑新增一个 `feishu` channel，不展开多平台 channel 生态
- 当前唯一调度 owner 是 `CronService`
- 调度存储路径固定为 `workspace/cron/jobs.json`
- 模型侧调度工具固定为 `cron_create / cron_list / cron_delete / cron_update`
- `/task` 已彻底移除，也不新增 `/cron` slash 命令
- `MemoryStore` 是 Dream 历史 owner
- 历史唯一来源固定为 `memory/history.jsonl`
- `HISTORY.md` 已不是当前实现的一部分
- skill 管理 owner 在 `agent/skills`
- 裸 `/skill` 已移除，只保留 `/skill list|install|uninstall`
- agent 默认工具现在已经包含 `list_skills` / `install_skill` / `uninstall_skill` / `cron_create` / `cron_list` / `cron_delete` / `cron_update`
- agent 默认工具中的 skill 组现在已经扩成 `list_skills` / `find_skills` / `install_skill` / `create_skill` / `uninstall_skill`
- 首次 `onboard` 默认 provider 是 `deepseek`
- 首次 `onboard` 默认模型是 `deepseek-v4-flash`
- `main` 分支的 `onboard` 不再预装任何业务 skill
- DeepSeek 的 tool-call transcript 协议修复固定收口在 provider 层
- DeepSeek 默认官方地址固定为 `https://api.deepseek.com`
- DeepSeek 现在有独立 `deepseek` provider，不再要求用户通过 `custom + apiBase` 伪装接入
- `deepseek-reasoner` 当前固定不走工具调用链路，带 tools 时直接返回明确错误
- Qwen 当前通过 `qwen` provider 接入 `https://dashscope.aliyuncs.com/compatible-mode/v1`
- Qwen 的 thinking 参数当前固定收口在 provider 层，包含 `enable_thinking / preserve_thinking`
- Qwen 在强制 `tool_choice` 时当前固定自动关闭 thinking
- Zhipu 当前通过 `zhipu` provider 接入 `https://open.bigmodel.cn/api/paas/v4`
- Zhipu 的 thinking 参数当前固定收口在 provider 层，包含 `extra_body.thinking / clear_thinking`
- Zhipu 在强制 `tool_choice` 时当前固定自动降级为 `auto`
- Moonshot 当前通过 `moonshot` provider 接入 `https://api.moonshot.cn/v1`
- Moonshot / Kimi 的 thinking 参数当前固定收口在 provider 层，包含 `extra_body.thinking / thinking.keep`
- Moonshot / Kimi 在强制 `tool_choice` 时当前固定自动降级为 `auto`
- SiliconFlow 当前通过 `siliconflow` provider 接入 `https://api.siliconflow.cn/v1`
- SiliconFlow 的 thinking 参数当前固定收口在 provider 层，包含 `extra_body.enable_thinking / thinking_budget`
- `Ctrl+C` 仍然退出交互进程
- `Esc` 现在是当前交互轮次的真实中断键
- `Esc` 的监听已固定为“孤立按键判定”，不会把终端控制序列残留到下一次输入
- `/stop` 已彻底移除，不再属于命令协议
- interrupted 历史只保留结构化事实，不保留半截自然语言
- `/new` 现在会清空短期消息和运行态 `metadata`
- active turn 的 CLI 渲染现在已收口为单写入器；tool hint 不再走 prompt 重绘通道
- `serve stdio` 复用当前外部事件名：`ready / progress / delta / stream_end / message / error`
- remote 当前事件面固定为：`ready / session_bound / turn_started / progress / delta / stream_end / message / turn_completed / interrupt_result / status_result / history_snapshot / session_list / task_delivered / sidebar_snapshot / resource_action_result / provider_state_snapshot / provider_list / provider_settings_updated / provider_updated / active_provider_changed / runtime_reloaded / error`
- remote 的 `ready` 事件当前额外携带 `provider_catalog + provider_state`
- remote provider 设置当前固定为 `remote-global` 持久化配置，provider identity 固定为 registry 槽位，不做动态 create/delete
- desktop 当前通过 `get_provider_state / list_providers / set_provider_settings / update_provider / set_active_provider / reload_runtime` 驱动 provider 设置 UI
- 当前 provider/model 切换的生效语义固定为 `reload_runtime`，不是热更新，也不是 session-bound
- 浏览器 demo 当前通过 `ws://.../ws?token=...` 联调 remote；正式客户端仍优先使用 `Authorization: Bearer ...`
- `AutoCompact.check_expired()` 当前已兼容 `SessionManager.list_sessions()` 的旧 `list[dict]` 和 remote 分页 `dict` 两种返回形状，避免 remote turn 在 `turn_started` 后因会话巡检异常中断
- 当前 `nomi-core` 协议依赖已升级到 `nomi-protocol v0.6.0`，remote provider management 命令集以该版本为基线
- CLI 根命令当前固定为：`onboard / agent / channel / remote / status`
- 当前已经有 `nomi channel login weixin`
- 微信 channel 第一版固定为个人微信私聊文本入口，不做流式、不做群聊、不做媒体
- `transcription` 当前只接 `qwen3-asr-flash`

## 3. 模块完成定义

`PLAN.md` 里的一个模块，只有同时满足下面四项才算完成：

1. 代码已经实现
2. 对应局部测试已经新增或更新，并且实际跑过
3. `docs/` 中对应模块文档已经新增或更新
4. 本文件已经回写当前状态、剩余事项和风险

## 4. 当前优先级

从现在开始，后续优先级固定为：

- `P0`：模块七/八后的缺陷修复和文档同步
- `P1`：系统级调度与 `heartbeat`
- `P1.5`：remote 正式 desktop shell 产品化

另外：

- 所有需要 `nomi-core + nomi-desktop` 共同推进的事项，单独维护在 `PLAN_DESKTOP_COLLAB.md`
- 本文件只保留 core 主仓自己的总路线，不再混写具体 desktop 协同执行清单

当前进展补充：

- remote 服务端 bridge 已完成
- `examples/remote-client/` 协议验证器已完成
- `nomi-desktop` 当前已经独立出主仓，桌面端后续产品化不再和 Python 主仓同目录推进
- `remote / desktop` 当前共享协议已经拆到独立 `nomi-protocol` 仓，core 和 desktop 通过外部依赖消费
- 当前已确认一个 desktop / channel 任务投递限制：
  - desktop 侧创建任务时，当前仍按 `desktop:{clientId}` session 写入任务目标
  - channel service 的 `CronService` 启动后只在本进程内持有已加载 job，不会自动热重载后续由 remote / desktop 新建的任务
  - 因此“在 desktop 创建任务，然后让 channel 默认收到提醒”目前不成立，属于当前代码事实，不是单纯前端显示问题
- 当前已完成一轮真实模型探测：
  - 以当前 `mimo-v2.5` 配置直接 `curl` OpenAI 兼容接口，测试了任务工具新增参数后的 tool-call 输出
  - `delivery_audience: "owner"` 与 `delivery_policy: { mode: "all", excluded_surfaces: [...] }` 两组字段都能被稳定产出
- 当前已完成一轮 remote session 管理协议与 core 收口：
  - `nomi-protocol` 已新增 `create_session / delete_session / session_created / session_deleted`
  - `list_sessions` 已扩成全 remote 视图，返回分页字段和完整 session 摘要
  - `bind_session / load_history / get_status / send_message / interrupt_turn` 对缺失 session 已统一返回 `session_not_found`
  - 下一步只剩 desktop 侧会话管理 UI 和交互接入
  - 多工具并列时，模型也能稳定选对 `task_create_after / at / daily / every`
  - 当前波动主要只在 `instruction` 措辞压缩，不在新增字段本身
- 若后续要实现“默认全平台提醒，但允许 AI 排除微信/桌面端”，当前更合适的方向是：
  - 协议层新增 `delivery_audience` 与 `delivery_policy`
  - agent 任务工具同步暴露这些参数
  - 但这属于 `nomi-protocol` 改动，按协作规则必须先得到用户明确批准后才能实施

另外还有两条边界必须固定下来：

- 模块一到模块八已经完成，后续默认只接受缺陷修复、文档同步和必要的小范围事实回写
- 不应把 status 面板增强、model catalog 动态化、skill marketplace、WebUI 包装之类事项插到系统级调度之前
- 当前仓库里的 `examples/remote-client/` 只承担 remote 协议验证职责，不等于正式桌面产品实现
- 当前 desktop 已移除全部 pet 代码路径；本文件中更后面的 pet 路线条目仅代表历史计划，不再代表当前代码事实

## 5. 已完成模块回顾

### 5.1 模块一：进程内 Runtime 收口

当前状态：`已完成`

已经落地的事实：

- 新增 `nomi/runtime/`
- CLI 通过 `NomiRuntime.from_config()` 统一装配主链路
- `RuntimeLifecycle` 统一承接 `start / wait / stop / close`
- 交互模式里，`AgentLoop` 生命周期已经回收到 runtime
- `nomi/facade.py` 已移除
- provider 装配入口已收口到 `nomi/providers/factory.py`

### 5.2 模块二：结构收口

当前状态：`已完成`

已经落地的事实：

- `config` 退回纯配置模型
- provider 解析移动到 `providers/resolution.py`
- `runtime` 暴露统一复用的薄控制 API
- `command` 拆成协议层和 handlers
- `AgentLoop` 暴露公开 owner API
- `agent/memory` 从单文件拆成 package
- 默认工具注册从 `AgentLoop` 内部初始化流程抽离

### 5.3 模块三：结构续收口

当前状态：`已完成`

已经落地的事实：

- `providers` 收口了 model catalog
- OAuth provider 整套移除
- CLI 拆成真实入口层
- `ContextBuilder` 退回纯上下文装配器
- `utils/helpers.py` 已删除并按 owner 分流
- `MemoryStore` 不再保留 `HISTORY.md` 兼容逻辑
- `pyproject.toml` 与 `uv.lock` 已同步到当前依赖状态

### 5.4 模块四：全局 Skill 管理收口

当前状态：`已完成`

已经落地的事实：

- `SkillRegistry` 退回只读 owner
- `SkillManager` 成为 skill 文件系统写操作 owner
- skill 安装支持本地目录、直接下载链接、Git 链接、GitHub `tree` 子目录链接
- skill 协议固定为 `/skill list|install|uninstall`
- 裸 `/skill` 已移除
- 本地 skill 安装在类 Unix 平台默认使用符号链接，在 Windows 平台使用复制目录
- agent 已可直接通过内置 tools 调用 skill 的安装、卸载和列表能力

### 5.5 模块五：真正的中断能力

当前状态：`已完成`

已经落地的事实：

- `Ctrl+C` 保持退出当前交互进程
- `Esc` 只在活跃回复期间生效
- `runtime` 新增统一控制面：`interrupt_session(session_id, reason="user_interrupt")`
- `AgentLoop.interrupt_session()` 已成为统一会话级中断入口
- `_dispatch()` 已把显式取消收口成 interrupted，而不是普通 error
- 中断终态固定为 `已中断当前回复。`
- session checkpoint 已固定 interrupted 语义
- `/stop` 已删除，不新增 `/interrupt` 或 `/cancel`

### 5.6 模块六：用 `cron` 整体替换 `task` 模块

当前状态：`已完成`

已经落地的事实：

- 旧 `tasks` 模块已经从主链路删除
- 新增 `nomi/cron/types.py`
- 新增 `nomi/cron/service.py`
- 新增调度工具文件 `nomi/agent/tools/cron.py`
- `AgentLoop` 改为持有 `CronService`
- `NomiRuntime` 删除 `list_tasks/remove_task`，改成 `list_cron_jobs/remove_cron_job`
- `/task` 已彻底移除，也不新增 `/cron`

- 调度规则已并入 `templates/IDENTITY.md`
- `workspace/cron/jobs.json` 成为唯一调度状态文件
- 这轮只做 `cron`，不引入 `heartbeat`
- 当前模型侧协议已经进一步收口为四个 CRUD 工具：
  - `cron_create`
  - `cron_list`
  - `cron_delete`
  - `cron_update`
- 模型侧不再暴露：
  - `action`
  - `name`
  - `cron_expr`
  - `tz`
  - `message / prompt / command`

### 5.7 模块六后的缺陷修复：CLI 输入污染与 `/new` 状态清理

当前状态：`已完成`

已经落地的事实：

- `EscInterruptWatcher` 不再把首个 `ESC` 字节直接当成中断
- `ESC [ 38 ; 1 R` 这类 CPR/ANSI 回复会被完整消费，不再把 `[38;1R` 残留到下一次输入
- `PromptSession` 的 output 已显式禁用 CPR，避免普通对话轮次把 `[23;1R` 漏成伪输入
- `/new` 现在会显式清空：
  - `messages`
  - `last_consolidated`
  - `session.metadata`
- `/new` 清理后仍然沿用原 session key 和会话文件，不额外创建新文件
- 所有模型可见文本现在都走 assistant 正文通道；`↳` 只保留 tool hint、工具过程提示和本地控制提示
- cron 等后台消息在用户正在输入时会先暂存，等当前输入提交后再顺序显示

### 5.8 模块六后的缺陷修复：CLI 渲染状态机收口

当前状态：`已完成`

已经落地的事实：

- active turn 期间的 spinner、正文流、tool hint 现在统一交给同一个 `StreamRenderer` 输出
- 当前轮次的 `↳` 提示不再走 `prompt_toolkit.run_in_terminal()`，只在等待输入时保留 prompt-safe 打印
- `tool hint` 在 bus 中已经改成独立的 `_tool_transition` 事件，不再和普通 `_progress` 混在一起
- `StreamRenderer` 的 spinner 生命周期已改成“单实例、按 phase 切换”，不再在一次工具轮里反复创建新 spinner 对象
- 工具轮现在会先结束当前正文流，再输出 `↳ tool(...)`，然后连续进入下一段 thinking，不再出现第一段 spinner 收尾后的可见空窗
- 当前轮次里的中断提示 `正在中断当前回复...` 也已经走 renderer 通道，避免 active turn 内再触发 prompt 重绘

## 6. 当前风险

当前最明确的风险只有这些：

1. interrupt 现在只保证 TTY 交互下的 `Esc`，还没有扩到未来多端入口
2. `runtime` 目前是进程内统一入口，不是独立后台服务
3. `cron` 仍然是应用内调度，不是系统级调度
4. model catalog 采用静态目录，模型事实变化需要显式更新仓库
5. 脏工作区下继续推进时，最容易把历史讨论误当成当前代码事实
6. 当前任务投递仍然偏单会话/单目标语义；在不改 protocol 和任务模型的前提下，desktop 新建任务无法自然收口成“默认全平台提醒”

## 7. 模块七：多端入口

当前状态：`已完成`

### 7.1 目标

把 Nomi 从“只有终端入口”推进成“多入口共享同一个 runtime”。

### 7.2 固定原则

这一轮已经落地的事实：

- 新增 `nomi serve stdio`
- `stdio` 入口只做 transport 包装
- `stdio` 入口直接复用：
  - `NomiRuntime.run_once()`
  - `interrupt_session()`
  - `reset_session()`
  - `get_status_snapshot()`
- 这条入口没有重新装配 `MessageBus + AgentLoop + provider`

## 8. 模块八：多通道能力

当前状态：`已完成（第一版）`

### 8.1 目标

把外部消息入口重新设计成协议适配层，而不是恢复旧 frozen 代码。

### 8.2 固定原则

后续多通道应该按下面的主链路接入：

```text
Channel Adapter
  ↓
Bus
  ↓
AgentLoop
```

这一轮已经落地的事实：

- 新增 `nomi/channels/base.py`
- 新增 `nomi/channels/manager.py`
- 新增 `nomi/channels/weixin.py`
- 新增 `nomi channels login weixin`
- 新增 `nomi serve channels`
- 第一版 `weixin` 使用稳定会话键 `weixin:{from_user_id}`
- 第一版 `weixin` 只做个人微信私聊文本收发
- 后续 channel 侧最多只再考虑一个 `feishu` 适配器
- 当前不做 TLS、token issuance、离线消息队列

## 9. 实际执行顺序

后续实际开工顺序固定为：

1. 先做模块七和模块八的缺陷修复、测试补齐、文档同步
2. 系统级调度与 `heartbeat` 另开模块，不回退到旧 task 体系
3. `P1.5` 的 desktop / pet 产品化按下面五个阶段推进，不并行扩协议
4. 模块一到模块八默认不再做结构性返工

## 10. `P1.5` Desktop / Pet 产品化路线

### 10.1 阶段一：交互闭环

目标：

- 让 desktop / pet 成为真正可用的聊天入口，而不是只显示 UI

当前应完成的事项：

- 用 `nomi remote run + npx tauri dev` 做多轮真实联调
- 验证 `pet -> send -> stream -> stop -> continue` 全链路
- 验证主窗口和 pet 共用同一 `desktop:{clientId}` session
- 验证 `task_delivered` 在 pet 上独立出现，不并入普通 turn
- 明确发送态、连接态、打断态、失败态
- 收口 `delta -> message -> turn_completed` 的展示一致性

这一阶段完成前，不进入动画层和系统托盘层。

### 10.2 阶段二：GUI 完善

目标：

- 把“能聊”升级成稳定好用的桌面 GUI

当前范围固定为：

- 优化主窗口的消息区、输入区、状态区布局
- 明确 assistant / task / progress / system 的视觉分层
- 优化 pet 的展开/收起、预览文本、快捷输入体验
- 收口窗口显示、聚焦、大小与默认位置行为
- 增加最小本地状态记忆：
  - 最近绑定 session
  - pet 展开状态
  - 窗口位置（如有必要）

这一阶段仍然不做角色动画、托盘和通知。

### 10.3 阶段三：Pet 动画与状态表达

目标：

- 从“气泡工具”升级成有桌面存在感的 pet

固定做法：

- 动画状态只从现有 desktop state 派生，不新建第二套 runtime
- 最小状态集固定为：
  - `idle`
  - `listening`
  - `thinking`
  - `streaming`
  - `alert`
  - `disconnected`
- 先做轻量状态动画：
  - idle 微动效
  - streaming 呼吸/波动
  - `task_delivered` 高优先级提醒态
  - disconnected / error 弱提示态

这一阶段不做：

- Live2D
- 骨骼动画
- 复杂角色素材系统
- 多宠物 / 换装 / 皮肤系统

### 10.4 阶段四：桌面系统集成

目标：

- 把 desktop 从开发态应用收口成更完整的桌面产品

当前规划范围：

- 系统托盘
- 开机自启
- 最小化到托盘
- 本地系统通知
- remote 断线重连
- 应用重启后的连接恢复
- `task_delivered` 的桌面通知呈现

这一阶段不改 remote 协议主设计，只允许做薄补齐。

### 10.5 阶段五：最终交付

目标：

- 形成一个可安装、可验证、可交付的 desktop 版本

必须同时完成：

- 桌面端文档补齐
- remote / desktop / pet 联调说明补齐
- 前端测试、Tauri 联调、真实人工交互验收补齐
- 打包发布流程明确
- 首次连接引导与常见故障排查文档补齐

交付前固定验收：

- 能连接 remote
- 能发送与接收流式回复
- 能中断当前轮并继续下一轮
- 能查看共享 session 历史
- 能收到任务提醒
- pet 与主窗口状态一致
- 重启后能恢复到可用状态
## 11. 一句话原则

下一阶段不要急着继续扩高级能力，而是先把 Nomi 做成：

```text
一个可中断、可复用、可接多入口的统一 runtime
```
