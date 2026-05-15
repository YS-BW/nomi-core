# 📝 Slash Commands

Slash command 是对话里的本地控制命令。它们以 `/` 开头，在进入模型之前就会被 Nomi 本地处理。

这类命令适合做确定性的本地控制，例如开新会话、查看状态、触发 Dream、管理 skill。

## 🌟 用户怎么用

在对话里直接输入：

```text
/status
/new
/dream
/skill list
```

这些内容不会发给模型，也不会被模型自由解释。

## 🧭 当前内置命令

| 命令 | 用途 |
|---|---|
| `/new` | 开始新会话 |
| `/restart` | 重启当前进程 |
| `/status` | 查看当前状态 |
| `/dream` | 手动触发 Dream 整理 |
| `/dream-log` | 查看最近一次 Dream 变更 |
| `/dream-restore` | 恢复到之前的 Dream 版本 |
| `/user-review` | 查看待确认的用户画像候选 |
| `/user-apply <id>` | 确认并写入一条用户画像 |
| `/user-reject <id>` | 忽略一条用户画像候选 |
| `/user-show` | 查看当前 `USER.md` |
| `/skill list` | 查看已安装 skills |
| `/skill install <source>` | 安装一个 skill |
| `/skill uninstall <name>` | 卸载一个 skill |
| `/help` | 查看可用命令 |

## ⚡ 优先级命令

`/restart` 和 `/status` 属于 priority command。

它们会在消息进入普通会话处理前优先执行，避免被当前 session 的长任务或模型调用影响。

## 🧠 和模型工具的区别

Slash command 是用户直接控制 Nomi 的本地命令。

工具是模型在回答过程中主动调用的能力。

例如：

- 用户输入 `/skill list`：直接走 slash command。
- 用户说“看看我有哪些 skill”：模型可以调用 skill 相关工具。

## 🧱 边界

- Slash command 不发给模型。
- instance 来源消息不会走普通用户快捷命令语义。
- 复杂业务能力优先做成工具或 CLI 命令，不要把 slash command 扩成另一个完整命令系统。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/command/router.py](../nomi/command/router.py#L15-L82) | 命令路由器 |
| [nomi/command/handlers/builtin.py](../nomi/command/handlers/builtin.py#L17-L72) | 内置命令注册 |
| [nomi/command/handlers/runtime.py](../nomi/command/handlers/runtime.py#L1-L83) | `/status`、`/restart`、`/help` |
| [nomi/command/handlers/session.py](../nomi/command/handlers/session.py#L1-L24) | `/new` |
| [nomi/command/handlers/dream.py](../nomi/command/handlers/dream.py#L1-L160) | Dream 命令 |
| [nomi/command/handlers/skills.py](../nomi/command/handlers/skills.py#L1-L98) | skill 命令 |
| [nomi/command/handlers/user_profile.py](../nomi/command/handlers/user_profile.py#L1-L66) | 用户画像命令 |
