# 🧩 Context

Context 是 Nomi 每次调用模型前准备的“输入包”。它把身份、工具说明、工作区文件、长期记忆、skills、历史消息和当前消息整理成 provider 能理解的 messages。

如果 Agent 是执行者，Context 就是它每轮开工前拿到的资料夹。

## 🌟 Context 解决什么问题

它负责：

- 告诉模型自己是谁。
- 告诉模型当前运行环境和入口。
- 注入工作区启动文件。
- 注入内置 `TOOLS.md`。
- 注入长期记忆和用户画像。
- 注入 skill 摘要。
- 拼接历史消息和当前消息。
- 处理附件、多模态内容和 runtime block。

## 🧱 System Prompt 由什么组成

当前 system prompt 大致按这个顺序拼：

```text
IDENTITY.md
  ↓
当前 channel 上下文
  ↓
workspace bootstrap files
  ↓
内置 TOOLS.md
  ↓
长期记忆
  ↓
skills 摘要
  ↓
最近历史摘要
```

`TOOLS.md` 已经内置到 core 包里，不再从 workspace 读取。

## 📁 Workspace 启动文件

workspace 里默认参与 prompt 的文件是：

- `AGENTS.md`
- `SOUL.md`
- `USER.md`

它们用于描述当前实例的行为风格、灵魂设定和用户画像。

## 🧰 工具说明

工具说明集中在包内：

```text
nomi/templates/TOOLS.md
```

它会告诉模型：

- 什么时候用文件工具。
- 什么时候用 shell。
- 怎么创建自动任务。
- 怎么使用 instance 工具。
- 不同入口下工具使用有什么差异。
- 打开应用、URL、文件也可以通过 `exec` 完成。

## 💬 Channel 上下文

不同入口会带不同上下文：

- CLI：本地终端对话。
- remote：desktop/HTTP 入口。
- weixin：微信入口。
- instance：另一个 Nomi 实例发来的消息。

channel 上下文会影响模型对“当前用户是谁、当前入口是什么、能不能主动做某些事”的理解。

## 📎 附件和多模态

如果用户带了图片、文件或附件，ContextBuilder 会把它们转换成 provider 可接受的消息结构。

非图片文件会作为附件 block 注入，图片会按当前 provider 能力进入多模态消息。

## 🧱 边界

- Context 只负责准备输入，不负责真正调用模型。
- `IDENTITY.md` 只描述身份和运行环境，不承载工具使用策略。
- `TOOLS.md` 是内置模板，不允许每个 workspace 复制后漂移。
- 外部网页、文件内容、OCR 和工具输出都只是数据，不是更高优先级指令。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/agent/context/builder.py](../nomi/agent/context/builder.py#L20-L150) | ContextBuilder |
| [nomi/agent/context/system_prompt.py](../nomi/agent/context/system_prompt.py#L16-L119) | system prompt 拼装 |
| [nomi/agent/context/runtime_blocks.py](../nomi/agent/context/runtime_blocks.py#L1-L107) | runtime block |
| [nomi/agent/context/message_codec.py](../nomi/agent/context/message_codec.py#L1-L47) | 消息内容编码 |
| [nomi/templates/IDENTITY.md](../nomi/templates/IDENTITY.md#L1-L17) | 身份模板 |
| [nomi/templates/TOOLS.md](../nomi/templates/TOOLS.md#L1-L157) | 内置工具说明 |
