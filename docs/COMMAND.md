# 📝 Slash Commands

slash 命令就是对话里的“本地控制口令” 🪄

它们的特点是：

- 以 `/` 开头
- 不发给模型 🚫🤖
- 在进入模型前由本地路由拦截

---

## 路由器

当前命令路由器是：

- [nomi/command/router.py](../nomi/command/router.py#L15-L82)

支持四类注册方式：

- `priority()`
- `exact()`
- `prefix()`
- `intercept()`

### 当前分发顺序

1. priority
2. exact
3. prefix
4. interceptors

这个顺序决定了为什么像 `/restart`、`/status` 会被更早处理。

---

## 当前内置命令

当前内置命令注册在：

- [nomi/command/handlers/builtin.py](../nomi/command/handlers/builtin.py#L17-L72)

完整列表：

| 命令 | 说明 |
|---|---|
| `/new` | 开始新会话 |
| `/restart` | 重启当前进程 |
| `/status` | 查看当前会话状态 |
| `/dream` | 手动触发 Dream |
| `/dream-log` | 查看 Dream 历史 |
| `/dream-restore` | 回滚 Dream 历史 |
| `/user-review` | 查看待确认画像候选 |
| `/user-apply <id>` | 确认一条画像 |
| `/user-reject <id>` | 拒绝一条画像 |
| `/user-show` | 查看当前 `USER.md` |
| `/skill list` | 查看 skills |
| `/skill install <source>` | 安装 skill |
| `/skill uninstall <name>` | 卸载 skill |
| `/help` | 查看帮助 |

---

## 会话命令

### `/new`

作用：

- 清空当前短期会话
- 把当前未归档消息交给 consolidator 后台归档

处理函数：

- [nomi/command/handlers/session.py](../nomi/command/handlers/session.py#L9-L24)

---

## Runtime 命令

### `/restart`

当前不是“重建一遍 Python 对象”，而是：

- 把重启提示写到环境变量
- `asyncio.create_task()` 延迟 1 秒
- `os.execv()` 原地重启当前进程

见 [nomi/command/handlers/runtime.py](../nomi/command/handlers/runtime.py#L15-L37)。

### `/status`

生成的是“当前会话运行状态”，不是全局 `nomi status` 表格。

内容格式化在：

- [nomi/command/runtime_status.py](../nomi/command/runtime_status.py#L8-L64)

处理函数：

- [nomi/command/handlers/runtime.py](../nomi/command/handlers/runtime.py#L40-L64)

### `/help`

帮助文案来自：

- [nomi/command/handlers/builtin.py](../nomi/command/handlers/builtin.py#L35-L46)

---

## Dream 命令

当前 Dream 命令实现文件：

- [nomi/command/handlers/dream.py](../nomi/command/handlers/dream.py#L10-L200)

### `/dream`

立即触发一次后台 Dream。

### `/dream-log`

查看最近一次或指定 SHA 的 Dream 变更。

### `/dream-restore`

如果不带参数：

- 列出最近可恢复版本

如果带参数：

- 恢复到指定 Dream 历史状态

---

## User Profile 命令

这组命令是当前 `USER.md` 画像确认链路的一部分。

处理文件：

- [nomi/command/handlers/user_profile.py](../nomi/command/handlers/user_profile.py#L9-L66)

### `/user-review`

列出当前 session 下待确认候选。

### `/user-apply <id>`

确认一条候选并写入 `USER.md`。

### `/user-reject <id>`

拒绝一条候选。

### `/user-show`

直接显示当前 `USER.md` 内容。

---

## Skill 命令

skill 命令统一走：

- [nomi/command/handlers/skills.py](../nomi/command/handlers/skills.py#L11-L98)

当前支持：

- `/skill list`
- `/skill install <source>`
- `/skill uninstall <name>`

它们最终会调用：

- `SkillRegistry`
- `SkillManager`

---

## 当前边界

`command/` 这层当前只负责：

- 命令协议
- 路由
- handler 组织

它不负责：

- 执行模型对话
- 管理 channel service
- 管理 CLI 渲染

如果把业务拼装逻辑继续塞进命令层，会让 slash 命令重新变得很难维护。
