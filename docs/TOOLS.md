# 🧰 Tools

Nomi 当前的工具系统已经接入主链路，不是外挂功能 🧰

默认工具会在 `AgentLoop` 初始化时统一注册：

- [nomi/agent/tools/bootstrap.py](../nomi/agent/tools/bootstrap.py#L26-L102)

---

## 当前默认工具集合

### 文件工具

| 工具 | 说明 |
|---|---|
| `read_file` | 读文本、图片、PDF |
| `write_file` | 写文件 |
| `edit_file` | 定位并编辑文件片段 |
| `list_dir` | 列目录 |

实现文件：

- [nomi/agent/tools/filesystem.py](../nomi/agent/tools/filesystem.py#L48-L220)

### 搜索工具

| 工具 | 说明 |
|---|---|
| `glob` | 按 glob 模式找文件 |
| `grep` | 按正则搜索内容 |

实现文件：

- [nomi/agent/tools/search.py](../nomi/agent/tools/search.py#L90-L220)

### Shell 工具

| 工具 | 说明 |
|---|---|
| `exec` | 执行 shell 命令，带安全限制 |

实现文件：

- [nomi/agent/tools/shell.py](../nomi/agent/tools/shell.py#L21-L220)

### Web 工具

| 工具 | 说明 |
|---|---|
| `web_search` | 搜索网页 |
| `web_fetch` | 抓取网页正文 |

实现文件：

- [nomi/agent/tools/web.py](../nomi/agent/tools/web.py#L75-L240)

### 图片工具

| 工具 | 说明 |
|---|---|
| `analyze_image` | 单独发起一次图片理解请求 |

实现文件：

- [nomi/agent/tools/image_analysis.py](../nomi/agent/tools/image_analysis.py#L16-L102)

### Cron 工具

| 工具 | 说明 |
|---|---|
| `cron_create` | 创建任务 |
| `cron_list` | 查看任务 |
| `cron_delete` | 删除任务 |
| `cron_update` | 更新任务 |

### Skill 工具

| 工具 | 说明 |
|---|---|
| `list_skills` | 查看 skills |
| `install_skill` | 安装 skill |
| `uninstall_skill` | 卸载 skill |

### Instance 关系工具

| 工具 | 说明 |
|---|---|
| `instance_invite_code` | 生成当前实例的邀请码 |
| `instance_invite` | 通过邀请码或 url/token 向另一个实例发起好友申请 |
| `instance_relation_list` | 查看当前实例登记的关系、备注、状态和权限 |
| `instance_relation_accept` | 接受一个实例好友申请 |
| `instance_relation_reject` | 拒绝一个实例好友申请 |
| `instance_relation_rename` | 设置或更新实例关系备注 |
| `instance_send_message` | 向已成为好友且具备 `chat` 权限的实例发送消息 |
| `instance_session_list` | 查看最近 instance 聊天会话 |
| `instance_session_get` | 读取某个 instance 会话的最近消息 |

实现文件：

- [nomi/agent/tools/instance_relations.py](../nomi/agent/tools/instance_relations.py#L19-L311)

这些工具由 `NomiRuntime` 挂载，因为它们需要访问当前实例的关系存储、remote token 和 InstanceChannel client：

- [nomi/runtime/app.py](../nomi/runtime/app.py#L1655-L1680)

工具使用说明不是 workspace 文件。`nomi/templates/TOOLS.md` 会由 system prompt builder 内置注入，`sync_workspace_templates()` 不再生成 `workspace/TOOLS.md`。

---

## 工具注册逻辑

`register_default_tools()` 会根据配置决定注册哪些工具：

- shell 工具只有 `tools.exec.enable = true` 才注册
- web 工具只有 `tools.web.enable = true` 才注册
- 其它默认工具始终注册

见 [nomi/agent/tools/bootstrap.py](../nomi/agent/tools/bootstrap.py#L55-L102)。

---

## 文件工具细节

### `read_file`

当前支持：

- 普通 UTF-8 文本
- PDF 文本抽取
- 图片读取并转成多模态内容块

同时会做这些保护：

- 拦截危险设备文件
- 文件未变化时返回“unchanged”占位
- 限制最大读取字符数

见 [nomi/agent/tools/filesystem.py](../nomi/agent/tools/filesystem.py#L78-L220)。

### 路径限制

文件工具统一通过 `_resolve_path()` 做路径解析和 allowed dir 限制：

- [nomi/agent/tools/filesystem.py](../nomi/agent/tools/filesystem.py#L21-L37)

---

## 搜索工具细节

`glob` 和 `grep` 都会跳过一批噪音目录，例如：

- `.git`
- `node_modules`
- `__pycache__`

搜索基类逻辑在 [nomi/agent/tools/search.py](../nomi/agent/tools/search.py#L90-L133)。

---

## Shell 工具细节

`exec` 当前是一个“受限制 shell 工具”，不是原始命令直通。

### 它会拦截的东西

例如：

- `rm -rf`
- `del /f /q`
- `rmdir /s`
- `dd if=`
- `shutdown`
- `reboot`
- `fork bomb`
- 直接覆盖 `history.jsonl` / `.dream_cursor`

拒绝规则定义在 [nomi/agent/tools/shell.py](../nomi/agent/tools/shell.py#L71-L87)。

### 工作区限制

如果开启：

```json
{
  "tools": {
    "restrictToWorkspace": true
  }
}
```

或者启用了 sandbox，`exec` 会加强工作目录限制。

---

## Web 工具细节

当前 `web_search` 支持多种后端：

- `duckduckgo`
- `tavily`
- `searxng`
- `jina`
- `brave`
- `kagi`

配置模型见 [nomi/config/schema/tools.py](../nomi/config/schema/tools.py#L12-L27)。

`web_fetch` 会做 URL 基础校验和正文抽取，不会把网页内容当成可信指令。

---

## MCP 扩展

Nomi 当前支持把外部 MCP server 包装成工具。

MCP 工具层在：

- [nomi/agent/tools/mcp.py](../nomi/agent/tools/mcp.py#L75-L260)

当前配置结构：

```json
{
  "tools": {
    "mcpServers": {
      "my-server": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"],
        "enabledTools": ["*"]
      }
    }
  }
}
```

配置模型定义在 [nomi/config/schema/tools.py](../nomi/config/schema/tools.py#L40-L59)。

当前支持协议：

- `stdio`
- `sse`
- `streamableHttp`

---

## 图片工具

`analyze_image` 的作用不是简单读图文件，而是显式发起一次独立多模态模型调用。

适合场景：

- 用户明确要“看图”
- 不想只靠 read_file 的占位文本

对应实现：[nomi/agent/tools/image_analysis.py](../nomi/agent/tools/image_analysis.py#L23-L102)

---

## 当前没有的工具

当前默认工具里已经没有：

- `notebook_edit`

如果文档里还写这个，就是过期信息。

---

## 当前边界

工具层当前的边界很明确：

- `bootstrap.py` 只负责默认装配
- 每个工具文件负责自己的协议与执行
- `ToolRegistry` 只负责注册和查找
- MCP 是扩展入口，不是把所有能力都堆在本地工具里

这套分层现在是比较干净的，文档也应该按这个事实来写。
