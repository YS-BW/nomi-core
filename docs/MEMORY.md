# 🧠 Memory

Nomi 的记忆系统现在早就不只是一个 `MEMORY.md` 文件了 🧠

它更像一套“分层记忆系统”：

当前主要有四块：

1. session 历史
2. 长期记忆文件
3. Dream 整理
4. 用户画像候选与确认

---

## 目录结构

默认工作区下，和记忆相关的文件大致是：

```text
~/.nomi/workspace/
├── SOUL.md
├── USER.md
├── memory/
│   ├── MEMORY.md
│   ├── history.jsonl
│   ├── user_profile_candidates.json
│   ├── .cursor
│   └── .dream_cursor
└── sessions/
```

记忆文件 owner 是 [nomi/agent/memory/store.py](../nomi/agent/memory/store.py#L110-L360)。

---

## 第一层：Session 历史

每个对话线程都有自己的 session 文件，保存在：

```text
~/.nomi/workspace/sessions/*.jsonl
```

由 `SessionManager` 管理：

- 获取或创建 session
- 从 JSONL 读取
- 写回 JSONL
- 维护 `last_consolidated`

见 [nomi/session/manager.py](../nomi/session/manager.py#L107-L219)。

### 会话 key

当前默认会话 key 规则：

- CLI：`cli:direct`
- 微信：`weixin:<chat_id>`
- Cron：根据 job payload 派生

`InboundMessage.session_key` 见 [nomi/bus/events.py](../nomi/bus/events.py#L21-L25)。

---

## 第二层：长期记忆文件

### `memory/MEMORY.md`

长期事实记忆，适合放：

- 项目长期背景
- 多轮对话后沉淀出的稳定信息
- 以后仍有价值的事实

读写接口：

- `read_memory()`：[nomi/agent/memory/store.py](../nomi/agent/memory/store.py#L168-L177)
- `write_memory()`：[nomi/agent/memory/store.py](../nomi/agent/memory/store.py#L179-L188)

### `SOUL.md`

Nomi 的行为风格和自我约束。  
这更像“AI 的人格与行事原则”，而不是用户画像。

读写接口：

- `read_soul()`：[nomi/agent/memory/store.py](../nomi/agent/memory/store.py#L190-L199)
- `write_soul()`：[nomi/agent/memory/store.py](../nomi/agent/memory/store.py#L201-L210)

### `USER.md`

只存“已确认”的用户画像，不存临时任务。

当前 `USER.md` 已经被结构化成机器可维护文档，由 MemoryStore 负责：

- 初始化默认结构
- 把结构渲染回 Markdown
- 按字段应用候选变更

相关代码：

- 文档读取：[nomi/agent/memory/store.py](../nomi/agent/memory/store.py#L364-L388)
- 文档渲染：[nomi/agent/memory/store.py](../nomi/agent/memory/store.py#L388-L449)
- 默认结构：[nomi/agent/memory/store.py](../nomi/agent/memory/store.py#L749-L781)

---

## 第三层：历史归档

`memory/history.jsonl` 不是 session 原始历史，而是长期归档历史。

它主要服务两件事：

- Consolidator 做历史压缩
- Dream 读取“最近还没被整理掉的历史”

system prompt 里“最近历史”段也是从这里来的：

- [nomi/agent/context/system_prompt.py](../nomi/agent/context/system_prompt.py#L109-L118)

---

## Consolidator 与 AutoCompact

### Consolidator

`Consolidator` 负责：

- 根据 token 窗口判断会话是否太长
- 把旧消息归档
- 维护 `last_consolidated`

### AutoCompact

`AutoCompact` 负责：

- 根据空闲时间自动触发 compact

对应装配：

- [nomi/agent/loop.py](../nomi/agent/loop.py#L168-L182)

---

## Dream

Dream 是当前主链路里的“长期记忆整理器”。

它的职责是：

- 读取当前长期记忆和历史
- 用模型分析哪些东西值得写回长期记忆
- 通过受限工具链修改 `SOUL.md`、`USER.md`、`MEMORY.md`
- 把这些文件的变更做 Git 版本记录

装配在 [nomi/agent/loop.py](../nomi/agent/loop.py#L183-L187)。

### Dream 跟踪哪些文件

当前 GitStore 只跟踪：

- `SOUL.md`
- `USER.md`
- `memory/MEMORY.md`

见 [nomi/agent/memory/store.py](../nomi/agent/memory/store.py#L135-L138)。

### Dream 触发方式

- 用户显式执行 `/dream`
- 后台逻辑触发 `trigger_dream_background()`

命令入口：[nomi/command/handlers/dream.py](../nomi/command/handlers/dream.py#L118-L133)

---

## 用户画像候选

这部分是当前记忆系统里最容易理解错、也最容易文档写偏的地方 ⚠️

### 当前真实行为

Nomi 现在不是“聊完一句话就偷偷改 `USER.md`” 🚫

真实流程是：

1. 识别本轮是否值得做画像抽取
2. 调用主 provider 做候选抽取
3. 把候选写入 `memory/user_profile_candidates.json`
4. 回复结尾附带提醒
5. 用户确认后才真正写入 `USER.md`

### 候选文件

```text
~/.nomi/workspace/memory/user_profile_candidates.json
```

对应字段结构见：

- `UserProfileCandidate`：[nomi/agent/memory/store.py](../nomi/agent/memory/store.py#L66-L108)

### 候选状态

当前状态包括：

- `pending`
- `applied`
- `rejected`
- `superseded`

### 候选抽取

由 `UserProfileService.extract_candidates()` 完成：

- [nomi/agent/memory/profile.py](../nomi/agent/memory/profile.py#L111-L172)

### 提醒生成

- [nomi/agent/memory/profile.py](../nomi/agent/memory/profile.py#L174-L199)

### 快捷确认

当当前 session 下确实有待确认候选，且用户下一条是短确认语句时，会直接命中快捷处理：

- `记住`
- `更新`
- `可以记`
- `不要记`
- `忽略`

逻辑见 [nomi/agent/memory/profile.py](../nomi/agent/memory/profile.py#L217-L234)。

### 命令确认

还支持这些显式命令：

- `/user-review`
- `/user-apply <id>`
- `/user-reject <id>`
- `/user-show`

命令处理见 [nomi/command/handlers/user_profile.py](../nomi/command/handlers/user_profile.py#L9-L66)。

---

## 当前主链路怎么接入画像

用户画像不是一个“边缘 feature”，它现在已经接入单轮处理流程。

关键接入点：

- quick action 检测：[nomi/agent/execution/processor.py](../nomi/agent/execution/processor.py#L282-L312)
- 对话后抽取提醒：[nomi/agent/execution/processor.py](../nomi/agent/execution/processor.py#L390-L402)
- reminder 构造：[nomi/agent/execution/processor.py](../nomi/agent/execution/processor.py#L462-L482)

---

## 当前边界

记忆层里几类 owner 要分清：

- `MemoryStore`：文件事实与读写
- `UserProfileService`：画像候选抽取 / 提醒 / 确认策略
- `Dream`：长期记忆整理
- `Consolidator`：session 压缩与归档

不要把它们重新揉成一个“超级记忆类”。
