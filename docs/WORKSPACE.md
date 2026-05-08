# 📁 Workspace

Workspace 是 Nomi 当前的运行世界 📁🌍

你也可以把它理解成：

> “这个 agent 眼下生活和工作的那块地盘。”

默认路径：

```text
~/.nomi/workspace
```

默认值定义在 [nomi/config/schema/agent.py](../nomi/config/schema/agent.py#L20-L38)。

路径解析在 [nomi/config/paths.py](../nomi/config/paths.py#L52-L61)。

---

## Workspace 和 `~/.nomi` 的关系

这里最容易搞混，所以一定要先分清两个层级 👇

### 1. `~/.nomi`

全局运行目录，通常放：

- `config.json`
- `logs/`
- `history/`
- `skills/`
- `weixin/`

### 2. `~/.nomi/workspace`

当前 agent 的工作区，通常放：

- bootstrap files
- memory
- sessions
- cron

这两个目录不要混着理解。

---

## 首次初始化会写哪些模板

`sync_workspace_templates()` 会在工作区里补这些文件：

- `AGENTS.md`
- `SOUL.md`
- `USER.md`
- `TOOLS.md`
- `memory/MEMORY.md`
- `memory/history.jsonl`

实现见 [nomi/utils/workspace.py](../nomi/utils/workspace.py#L10-L61)。

---

## 典型目录结构

```text
~/.nomi/workspace/
├── AGENTS.md
├── SOUL.md
├── USER.md
├── TOOLS.md
├── memory/
│   ├── MEMORY.md
│   ├── history.jsonl
│   ├── user_profile_candidates.json
│   ├── .cursor
│   └── .dream_cursor
├── sessions/
│   └── *.jsonl
└── cron/
    └── jobs.json
```

---

## 这些文件分别做什么

| 文件 | 作用 |
|---|---|
| `AGENTS.md` | 当前工作区的项目规则与开发说明 |
| `SOUL.md` | AI 自我约束和风格 |
| `USER.md` | 已确认的用户画像 |
| `TOOLS.md` | 工具使用规则 |
| `memory/MEMORY.md` | 长期事实记忆 |
| `memory/history.jsonl` | 长期归档历史 |
| `memory/user_profile_candidates.json` | 待确认画像候选 |
| `sessions/*.jsonl` | 短期会话 |
| `cron/jobs.json` | 应用内调度任务 |

---

## Workspace 和 Session 的区别

### 换 session

改变的是：

- 当前会话线程

不改变：

- 记忆文件
- cron
- skills
- bootstrap files

### 换 workspace

改变的是：

- 整套运行世界

包括：

- 会话文件
- 长期记忆
- cron 存储
- bootstrap files

所以 `--workspace` 的影响远大于 `--session`。

---

## GitStore

工作区初始化时还会尝试为记忆文件建立 GitStore：

- 跟踪 `SOUL.md`
- 跟踪 `USER.md`
- 跟踪 `memory/MEMORY.md`

见 [nomi/utils/workspace.py](../nomi/utils/workspace.py#L50-L58)。

这就是为什么 Dream 可以做版本查看和回滚。

---

## 当前边界

Workspace 当前承载的是“agent 的运行世界”，不是整个全局配置目录。

所以：

- `config.json` 在 `~/.nomi`
- 登录态在 `~/.nomi/weixin`
- logs 在 `~/.nomi/logs`
- 只有 agent 相关状态在 `workspace`

文档里如果把这些全写进 workspace，会让用户误解路径层级。
