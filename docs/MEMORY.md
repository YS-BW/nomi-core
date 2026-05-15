# 🧠 Memory

Memory 是 Nomi 的长期记忆系统。它不只是一个文件，而是由会话历史、长期记忆、Dream 整理和用户画像候选共同组成。

Session 负责“这条对话刚聊了什么”；Memory 负责“长期应该记住什么”。

## 🌟 Memory 包含什么

当前主要有四层：

- Session 历史：每条会话的短期上下文。
- `MEMORY.md`：长期记忆正文。
- Dream：对长期记忆和人格文件做整理。
- `USER.md`：用户画像和偏好。

## 📁 文件位置

默认工作区下：

```text
<instance-root>/workspace/
├── SOUL.md
├── USER.md
└── memory/
    ├── MEMORY.md
    ├── history.jsonl
    ├── user_profile_candidates.json
    ├── .cursor
    └── .dream_cursor
```

会话历史在：

```text
<instance-root>/sessions/
```

## 👤 用户画像

当用户表达长期偏好时，Nomi 会尝试抽取用户画像候选。

例如：

```text
以后你回答我直接一点。
我常用 Python 和 TypeScript。
我不喜欢太长的解释。
```

这类内容不会直接写入 `USER.md`，而是先变成候选，再由用户确认。

用户可以：

```text
记住。
不要记。
/user-review
/user-apply <id>
/user-reject <id>
```

## 🌙 Dream

Dream 是手动触发的记忆整理能力。

常用命令：

```text
/dream
/dream-log
/dream-restore
```

Dream 会整理 `SOUL.md`、`USER.md`、`memory/MEMORY.md`，并通过内部 GitStore 保留可回滚历史。

## 🧠 和 Context 的关系

每轮调用模型时，ContextBuilder 会读取长期记忆和用户画像，把它们注入 system prompt。

这让模型在不同会话里也能知道用户长期偏好。

## 🧱 边界

- Nomi 不应该把临时安排、当天情绪、一次性提醒写进长期画像。
- 用户画像候选需要用户确认。
- 清空 session 不等于清空长期记忆。
- Dream 是整理，不是任意重写用户事实。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/agent/memory/store.py](../nomi/agent/memory/store.py#L110-L180) | MemoryStore 文件入口 |
| [nomi/agent/memory/profile.py](../nomi/agent/memory/profile.py#L87-L230) | 用户画像候选抽取和提醒 |
| [nomi/agent/memory/dream.py](../nomi/agent/memory/dream.py#L1-L202) | Dream 整理 |
| [nomi/agent/memory/consolidator.py](../nomi/agent/memory/consolidator.py#L1-L272) | 会话归档整理 |
| [nomi/agent/memory/autocompact.py](../nomi/agent/memory/autocompact.py#L1-L158) | 自动压缩 |
| [nomi/command/handlers/user_profile.py](../nomi/command/handlers/user_profile.py#L1-L66) | 用户画像 slash 命令 |
| [nomi/command/handlers/dream.py](../nomi/command/handlers/dream.py#L1-L160) | Dream slash 命令 |
