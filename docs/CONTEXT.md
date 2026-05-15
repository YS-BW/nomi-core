# 🧩 Context

Nomi 每次调用模型前，都要先把“眼前这摊信息”整理成一组标准 messages 🧺

简单说，就是先把该带给模型的内容打包好，再真正发请求。

这套逻辑当前主要在 `nomi/agent/context/` 下：

```text
nomi/agent/context/
├── builder.py
├── system_prompt.py
├── runtime_blocks.py
└── message_codec.py
```

---

## ContextBuilder 的职责

`ContextBuilder` 负责两件事，理解起来很简单：

1. 生成 system prompt
2. 生成本轮调用的完整 messages 数组

对应代码：[nomi/agent/context/builder.py](../nomi/agent/context/builder.py#L20-L148)

---

## System Prompt 的组成

当前 system prompt 不是一个静态字符串，而是拼出来的：

```text
IDENTITY.md
  ↓
当前 channel 对应模板
  ↓
工作区 bootstrap files
  ↓
内置 TOOLS.md
  ↓
长期记忆
  ↓
skills 摘要
  ↓
最近历史
```

真正拼装发生在 [nomi/agent/context/system_prompt.py](../nomi/agent/context/system_prompt.py#L40-L50)。

### 组成来源

#### 1. 身份与运行环境

来自 `IDENTITY.md` 模板，包含：

- 当前工作区路径
- 当前系统与 Python 版本
- 当前平台规则
- 当前 channel 环境说明

见 [nomi/agent/context/system_prompt.py](../nomi/agent/context/system_prompt.py#L52-L91)。

`IDENTITY.md` 只描述身份、运行环境和入口上下文，不承载具体工具使用策略。

#### 2. Bootstrap files

当前默认加载这些工作区文件：

- `AGENTS.md`
- `SOUL.md`
- `USER.md`

定义在 [nomi/agent/context/system_prompt.py](../nomi/agent/context/system_prompt.py#L16-L16)。

`TOOLS.md` 由 [nomi/templates/TOOLS.md](../nomi/templates/TOOLS.md#L1-L157) 作为包内模板注入，不再从 workspace 读取。工具选择、执行规则、不同 channel 下的工具使用方法、自动任务、instance 工具和工作区纪律都集中放在这里，避免每个实例的 workspace 复制一份后漂移。

#### 3. 长期记忆

来自 `MemoryStore.get_memory_context()`，最终通常是：

- `MEMORY.md`
- `SOUL.md`
- `USER.md`

经 MemoryStore 整理后写入 prompt。

#### 4. Skills 摘要

不是直接把 skill 正文全塞进去，而是只注入 metadata 摘要。

见 [nomi/agent/skills/registry.py](../nomi/agent/skills/registry.py#L54-L79)。

#### 5. 最近历史

来自 `memory/history.jsonl` 中“自上次 Dream 游标之后还没被吸收的历史”。

见 [nomi/agent/context/system_prompt.py](../nomi/agent/context/system_prompt.py#L109-L118)。

---

## Channel 专属模板

当前 system prompt 会根据入口 channel 选择不同模板：

- `cli` -> `CHANNEL_CLI.md`
- `weixin` -> `CHANNEL_WEIXIN.md`
- 其它 / 未知 -> 空字符串

对应代码：[nomi/agent/context/system_prompt.py](../nomi/agent/context/system_prompt.py#L69-L77)

这里有一个很重要的现实：

- 微信当前仍然要求模型输出 `<part>`
- 这是写在 `CHANNEL_WEIXIN.md` 里的强约束
- channel 发送层只是按 `<part>` flush，不做语义切段

模板文件：

- [nomi/templates/CHANNEL_WEIXIN.md](../nomi/templates/CHANNEL_WEIXIN.md#L1-L150)

---

## 本轮用户消息怎么组装

本轮不是简单发一条 `"user": "xxx"`，而是会先插入 runtime context block。

`build_messages()` 当前会做这些事：

1. 构造 runtime context
2. 把用户文本和多模态内容编码成标准内容块
3. 如果上一条也是同 role，做消息合并

对应代码：[nomi/agent/context/builder.py](../nomi/agent/context/builder.py#L66-L115)

---

## Runtime Context

runtime context 是本轮有效、但不适合进入长期 system prompt 的信息。

当前主要包括：

- channel
- chat_id
- timezone
- session summary
- 附件文本说明

构造在：

- [nomi/agent/context/runtime_blocks.py](../nomi/agent/context/runtime_blocks.py#L18-L37)

它会被放进当前用户消息，而不是 system prompt。

这样做的目的很明确：

- 避免把短期运行态污染长期 prompt 主干
- 避免附件路径这类瞬时信息进入长期记忆上下文

---

## 多模态内容编码

图片、附件、多段文本不是直接手搓结构，而是统一走 `message_codec.py`。

当前事实：

- 图片文件可转成 provider 可接受的 image block
- 非图片附件只会进入 runtime metadata 文本说明
- 会话落盘时，内嵌 data URL 图片会被替换成占位文本，避免 session 膨胀

相关代码：

- 图片 MIME 识别：[nomi/agent/context/message_codec.py](../nomi/agent/context/message_codec.py#L9-L19)
- 会话落盘清洗：[nomi/agent/execution/processor.py](../nomi/agent/execution/processor.py#L579-L654)

---

## Assistant 消息如何写回

助手消息不是随便 append 一个 dict，而是统一走：

- `build_assistant_message()`

这样做是为了统一处理：

- `content`
- `tool_calls`
- `reasoning_content`
- `reasoning_items`
- `thinking_blocks`

见 [nomi/agent/context/builder.py](../nomi/agent/context/builder.py#L128-L147)。

---

## 当前边界

`context/` 这层当前只负责“把事实组织成模型输入”。

它不负责：

- 决定要不要写记忆
- 决定要不要执行工具
- 管理 channel 协议
- 改动 session 文件

如果后续把这些逻辑塞回 `context/`，模块会再次变回一团。
