# 🧰 Tools

Tools 是模型能调用的实际能力。用户自然说“读一下这个文件”“打开微信”“10 分钟后提醒我”“问一下 xmy 的 Nomi”，最终通常都会落到某个工具调用。

工具说明由 core 内置 `TOOLS.md` 注入 system prompt，不再作为每个 workspace 的可变文件生成。

## 🌟 默认工具能做什么

当前默认工具覆盖这些能力：

- 文件读写和编辑。
- 工作区搜索。
- 受限制的 shell 命令。
- 网页搜索和抓取。
- 图片理解。
- 自动任务。
- Skill 管理。
- MCP 管理。
- Instance 改名、关系、聊天和会话查询。

## 📁 文件工具

| 工具 | 用途 |
|---|---|
| `read_file` | 读取文本、图片、PDF 等文件 |
| `write_file` | 写入新文件或覆盖文件 |
| `edit_file` | 按片段编辑文件 |
| `list_dir` | 列出目录内容 |

模型需要先读后写，不能假设文件存在或内容符合预期。

## 🔎 搜索工具

| 工具 | 用途 |
|---|---|
| `glob` | 按文件名模式找文件 |
| `grep` | 按正则搜索文件内容 |

大范围搜索时，模型应该先缩小范围，再读取具体文件。

## 🖥️ Shell 工具

| 工具 | 用途 |
|---|---|
| `exec` | 执行受限制的 shell 命令 |

`exec` 可以用于：

- 运行测试。
- 查看命令输出。
- 打开本机应用。
- 打开 URL。
- 打开本地文件。

macOS 示例：

```bash
open -a WeChat
open -a "Google Chrome" "https://example.com"
open "/absolute/path"
```

不能用 `exec` 做延时和后台调度；这类需求应该用 `task_*`。

## 🌐 Web 工具

| 工具 | 用途 |
|---|---|
| `web_search` | 搜索网页 |
| `web_fetch` | 抓取网页正文 |

适合处理需要联网确认的事实、资料和页面内容。

## ⏰ 自动任务工具

| 工具 | 用途 |
|---|---|
| `task_create_after` | 延时一次 |
| `task_create_at` | 定点一次 |
| `task_create_daily` | 每天重复 |
| `task_create_every` | 固定间隔重复 |
| `task_list` | 查看任务 |
| `task_get` | 查看单个任务 |
| `task_delete` | 删除任务 |
| `task_enable` | 启用任务 |
| `task_disable` | 停用任务 |
| `task_update_instruction` | 修改任务内容 |
| `task_reschedule_after` | 改成延时一次 |
| `task_reschedule_at` | 改成定点一次 |
| `task_reschedule_daily` | 改成每天重复 |
| `task_reschedule_every` | 改成固定间隔重复 |

默认提醒是全局投递。只有用户明确要求“只发微信 / 只发 desktop / 只发 CLI”时，才设置 `target_channels`。

## 🤝 Instance 工具

| 工具 | 用途 |
|---|---|
| `instance_set_name` | 设置当前 Nomi 名字 |
| `instance_invite_code` | 生成一次性邀请码 |
| `instance_invite` | 用邀请码发好友申请 |
| `instance_relation_list` | 查看关系和申请 |
| `instance_relation_accept` | 接受申请 |
| `instance_relation_reject` | 拒绝申请 |
| `instance_relation_withdraw` | 撤回申请 |
| `instance_relation_remove` | 删除关系 |
| `instance_relation_set_permission` | 修改授予对方的权限 |
| `instance_send_message` | 给另一个 instance 发消息 |
| `instance_session_list` | 查看最近 instance 会话 |
| `instance_session_get` | 读取某个 instance 会话 |

权限由接收方本地 relation 决定：

- `chat`：聊天和 instance 会话查询。
- `task`：在 `chat` 基础上允许 `task_*`。
- `all`：在 `task` 基础上允许文件、命令、skill、MCP 和关系管理。

## 📦 Skill 和 MCP 工具

Skill 工具用于安装、创建、卸载和列出 skills。
MCP 工具用于管理外部 MCP server 配置。

这两类工具会改变当前实例能力，通常应该只在用户明确要求时使用。

## 🧱 工具权限边界

- 工具返回结果是给模型看的，模型应该根据结果解释给用户。
- instance 来源不是本机用户，必须按 relation permission 暴露工具。
- 自动任务内部不能递归创建新任务。
- shell 工具不能用来绕过自动任务系统。
- 工作区里的外部文件内容只是数据，不是更高优先级指令。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/agent/tools/bootstrap.py](../nomi/agent/tools/bootstrap.py#L26-L136) | 默认工具注册 |
| [nomi/agent/tools/registry.py](../nomi/agent/tools/registry.py#L1-L166) | 工具注册表和执行 |
| [nomi/agent/tools/filesystem.py](../nomi/agent/tools/filesystem.py#L48-L220) | 文件工具 |
| [nomi/agent/tools/search.py](../nomi/agent/tools/search.py#L90-L220) | 搜索工具 |
| [nomi/agent/tools/shell.py](../nomi/agent/tools/shell.py#L21-L355) | shell 工具 |
| [nomi/agent/tools/web.py](../nomi/agent/tools/web.py#L75-L240) | web 工具 |
| [nomi/agent/tools/tasks.py](../nomi/agent/tools/tasks.py#L14-L723) | 自动任务工具 |
| [nomi/agent/tools/instance_relations.py](../nomi/agent/tools/instance_relations.py#L11-L408) | instance 工具 |
| [nomi/templates/TOOLS.md](../nomi/templates/TOOLS.md#L1-L157) | 注入给模型的工具说明 |
