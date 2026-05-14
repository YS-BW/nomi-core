# 🍌 Nomi

> 一个终端原生的个人 AI 助手。  
> 你可以在命令行里和它对话，也可以把它接到微信上 🤖💬  
> 现在也可以把它作为远程 runtime，给桌面壳连接使用 🖥️✨  
> 它能帮你读代码、改文件、跑命令、查网页、记住长期信息、创建定时提醒 ⏰🧠

---

## 项目定位

Nomi 可以先把它理解成一个“住在终端里的 AI 搭子” 🍌

当前产品形态很明确：

- 一个以终端为主入口的 AI 助手
- 一个统一的进程内 runtime
- 一个真实的多实例运行模型
- 一个真实可运行的 Agent 主链路
- 一个单入口外部 channel 子系统
- 一套可持续积累的记忆、工具、skills 和 cron 能力

它不是一个“大而全的 agent 平台” 🧱  
也不是一个套了 AI 名字的 Web 壳子 🌐

当前代码的核心方向也很直接：

- 把主链路做扎实
- 把模块边界做清楚
- 保持代码、测试、文档一致

---

## 核心能力

- 聊天与交互：像终端里的常驻 AI 助手一样工作 ✨
- 终端交互：流式输出、Markdown 渲染、命令历史、`Esc` 中断当前回复
- 文件与代码操作：读文件、写文件、编辑文件、搜索代码、列目录
- 命令执行：受约束的 shell 执行工具
- Web 能力：搜索网页、抓取网页正文
- 长期记忆：`MEMORY.md`、`SOUL.md`、`USER.md`
- 用户画像：对话后抽取候选，确认后写入 `USER.md`
- Skills：全局安装和复用任务说明包
- 定时任务：AI 自己创建 cron / reminder
- 微信接入：扫码登录、前台/后台运行、日志跟随、分段发送、typing 状态 💬📱
- 远程壳接入：服务器侧 HTTP API + SSE adapter，可供桌面端查询、操作并实时订阅消息与状态 🖥️🔌

---

## 当前仓库边界

当前 monorepo 已经开始按三仓方向收口：

- `nomi-core`
  - 当前就是这份 Python 主仓
- `nomi-desktop`
  - 当前已经拆到独立桌面仓
- `nomi-protocol`
  - 当前作为独立协议仓，通过 GitHub 依赖接入

这一步的目标不是一次性物理拆仓，而是先把 desktop 和 core 共用的 wire contract 收成单一事实源，避免协议继续散落在两侧实现里。

---

## 安装

### 环境要求

- Python `>= 3.11`
- 推荐使用 [uv](https://docs.astral.sh/uv/)

### 安装依赖

```bash
git clone <your-repo-url> nomi
cd nomi
uv sync
```

如果你要跑测试：

```bash
uv sync --extra dev
```

### 安装成全局命令

```bash
uv tool install -e .
nomi --version
```

项目入口定义在 [pyproject.toml](./pyproject.toml#L1-L114)。

---

## 快速开始

完整日常命令见 [Nomi 操作手册](./docs/OPERATIONS.md)。

### 1. 初始化配置

```bash
nomi onboard
```

`onboard` 会：

- 默认初始化 `default -> ~/.nomi`
- 创建实例级 `config.json`
- 创建实例级工作区目录
- 同步工作区模板文件

如果你要创建第二实例，现在应该直接走：

```bash
nomi instance create team-a
nomi onboard --instance team-a
```

命令入口在 [nomi/cli/commands/onboard.py](./nomi/cli/commands/onboard.py#L16-L125)。

### 2. 填入模型配置

当前默认 provider 是 `mimo`，默认模型从 `providers.mimo.model` 读取，基础地址由 provider 注册表锁定。

最小可用配置可以是：

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nomi/workspace",
      "provider": "mimo",
      "timezone": "Asia/Shanghai"
    }
  },
  "providers": {
    "mimo": {
      "apiKey": "你的 key",
      "tokenPlanApiKey": "",
      "model": "mimo-v2.5",
      "extraHeaders": null
    }
  },
  "tools": {
    "web": {
      "enable": true
    },
    "exec": {
      "enable": true,
      "timeout": 60
    },
    "restrictToWorkspace": false,
    "mcpServers": {}
  },
  "transcription": {
    "apiKey": ""
  },
  "channel": {
    "kind": ""
  }
}
```

获取小米 API Key：

- [小米 MiMo API Keys](https://platform.xiaomimimo.com/console/api-keys)

默认值定义在 [nomi/config/schema/agent.py](./nomi/config/schema/agent.py#L20-L43)、[nomi/config/schema/provider.py](./nomi/config/schema/provider.py#L10-L36) 和 [nomi/config/schema/root.py](./nomi/config/schema/root.py#L18-L38)。

### 3. 启动终端交互

```bash
nomi
```

或者：

```bash
nomi agent
```

CLI 根入口在 [nomi/cli/app.py](./nomi/cli/app.py#L25-L87)，交互主命令在 [nomi/cli/commands/agent.py](./nomi/cli/commands/agent.py#L23-L128)。

### 4. 发送单条消息

```bash
nomi agent -m "帮我看看当前目录结构"
```

---

## 微信接入

Nomi 当前只有一个外部 channel 入口：`nomi channel`。  
底层当前只实现了 `weixin`。

`channel` / `remote` / `status` / `onboard` 现在都支持：

- `--instance`
- `--instance-root`

### 启用微信

在配置中设置：

```json
{
  "channel": {
    "kind": "weixin",
    "weixin": {
      "allowFrom": ["*"],
      "baseUrl": "https://ilinkai.weixin.qq.com",
      "routeTag": null,
      "token": "",
      "stateDir": "",
      "pollTimeout": 35
    }
  }
}
```

配置模型见 [nomi/config/schema/channel.py](./nomi/config/schema/channel.py#L12-L36)。

### 登录

```bash
nomi channel login
```

这条命令当前会：

- 清除已保存的微信登录态
- 清空当前工作区下的 session 持久化
- 拉起新的二维码登录流程
- 在终端输出登录链接，并尽量直接打印二维码

实现见 [nomi/channel/adapters/weixin/channel.py](./nomi/channel/adapters/weixin/channel.py#L488-L546) 和 [nomi/channel/adapters/weixin/channel.py](./nomi/channel/adapters/weixin/channel.py#L547-L621)。

### 启用与运行

```bash
nomi channel enable weixin
nomi instance restart
```

特点：

- `channel enable` 只修改实例配置
- `instance restart` 启动或重启唯一实例 runtime
- 如果微信已有登录态，runtime 会挂载 weixin adapter

入口在 [nomi/cli/commands/channel.py](./nomi/cli/commands/channel.py#L1-L123)。

### 查看状态与日志

```bash
nomi channel status
nomi instance log
```

统一日志文件：

```text
~/.nomi/logs/runtime-service.log
```

### 停用

```bash
nomi channel disable
nomi instance restart
```

### 运行约束

当前产品规则是：

- `instance` 是唯一后台运行主体
- `remote` 和 `channel` 都是挂在 instance runtime 上的 adapter
- 同一实例只允许一个 runtime 进程

状态管理见 [nomi/runtime/service/state.py](./nomi/runtime/service/state.py#L1-L306)。

---

## Remote Demo

如果你想先验证“服务器 runtime + 远程壳”这条链路，现在仓库里已经有一个最小网页验证器 🖥️✨

### 1. 启用 remote 配置

```json
{
  "remote": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 8765,
    "authToken": ""
  }
}
```

使用 `nomi remote token` 查看或自动生成 token。remote 配置变化通过 `nomi instance restart` 生效。

### 2. 启动 instance runtime

```bash
nomi remote enable
nomi instance restart
```

### 3. 启动 demo 静态页

```bash
uv run python -m http.server 8080 -d examples/remote-client
```

### 4. 浏览器打开

```text
http://127.0.0.1:8080
```

这个 demo 当前可以直接验证：

- 通过 HTTP 拉取 bootstrap、session 列表和历史
- 通过 HTTP 发送消息和中断当前轮
- 通过 SSE 接收流式回复、session 变更和任务投递事件
- 打开微信会话时实时看到 session 新消息

更完整说明见 [docs/REMOTE.md](./docs/REMOTE.md) 和 [examples/remote-client/README.md](./examples/remote-client/README.md)。

---

## Desktop Shell

正式桌面端现在已经独立为 `nomi-desktop` 仓库。

当前这份 `nomi-core` 仓只保留：

- `nomi remote`
- 对 `nomi-protocol` 的 Python 依赖接入
- remote server / runtime / tests / docs

桌面端本体不再和 Python 主仓同目录维护。

当前 `nomi-core` 默认通过 GitHub 依赖安装协议仓：

```bash
uv sync
```

---

## 状态查看

```bash
nomi status
```

当前会展示：

- 当前配置文件路径
- 工作区路径
- 默认 provider
- 默认模型
- 默认时区
- channel 是否启用
- channel owner
- channel 是否在运行
- channel 是否已登录
- channel 日志路径

命令入口在 [nomi/cli/commands/status.py](./nomi/cli/commands/status.py#L13-L37)，状态聚合在 [nomi/cli/support/status.py](./nomi/cli/support/status.py#L29-L75)。

---

## 交互命令

在 `nomi agent` 里可以使用这些 slash 命令：

| 命令 | 说明 |
|---|---|
| `/new` | 开始新会话 |
| `/restart` | 原地重启当前 nomi 进程 |
| `/status` | 查看当前会话运行状态 |
| `/dream` | 手动触发一次 Dream |
| `/dream-log` | 查看最近一次 Dream 变更 |
| `/dream-restore` | 恢复之前的 Dream 版本 |
| `/user-review` | 查看待确认的用户画像候选 |
| `/user-apply <id>` | 确认一条画像并写入 `USER.md` |
| `/user-reject <id>` | 忽略一条画像候选 |
| `/user-show` | 查看当前 `USER.md` |
| `/skill list` | 查看已安装 skills |
| `/skill install <source>` | 安装一个 skill |
| `/skill uninstall <name>` | 卸载一个 skill |
| `/help` | 查看帮助 |

命令注册见 [nomi/command/handlers/builtin.py](./nomi/command/handlers/builtin.py#L17-L72)。

---

## 工作区

默认工作区：

```text
~/.nomi/workspace
```

首次初始化后，通常会有这些文件：

```text
~/.nomi/workspace/
├── AGENTS.md
├── SOUL.md
├── USER.md
├── TOOLS.md
├── memory/
│   ├── MEMORY.md
│   ├── history.jsonl
│   └── user_profile_candidates.json
├── sessions/
└── cron/
    └── jobs.json
```

模板同步逻辑在 [nomi/utils/workspace.py](./nomi/utils/workspace.py#L10-L61)。

---

## 记忆系统

Nomi 当前有几层和“记住事情”相关的能力：

- `sessions/*.jsonl`：每个会话的原始对话历史
- `memory/history.jsonl`：长期归档历史
- `memory/MEMORY.md`：长期事实记忆
- `SOUL.md`：AI 行为与人格倾向
- `USER.md`：已确认的用户画像
- `memory/user_profile_candidates.json`：待确认画像候选

当前 `USER.md` 不是静默自动改写的。真实流程是：

1. 一轮对话完成后尝试抽取“长期用户画像候选”
2. 候选先写入 `user_profile_candidates.json`
3. 回复末尾附带提醒
4. 用户通过自然语言“记住”或 `/user-apply` 确认
5. 确认后才写回 `USER.md`

对应实现：

- 候选存储：[nomi/agent/memory/store.py](./nomi/agent/memory/store.py#L234-L401)
- 候选抽取与提醒：[nomi/agent/memory/profile.py](./nomi/agent/memory/profile.py#L87-L341)
- 主链路接入：[nomi/agent/execution/processor.py](./nomi/agent/execution/processor.py#L390-L515)

---

## Provider

当前默认 provider 是 `custom`，适合直接接 OpenAI 兼容接口。  
另外还内置了多种 provider 规格和识别规则。

当前配置模型里实际存在的 provider 段包括：

- `custom`
- `azure_openai`
- `anthropic`
- `openai`
- `openrouter`
- `zhipu`
- `vllm`
- `ollama`
- `ovms`
- `moonshot`
- `aihubmix`
- `siliconflow`
- `volcengine`
- `volcengine_coding_plan`
- `byteplus`
- `byteplus_coding_plan`

配置字段定义在 [nomi/config/schema/provider.py](./nomi/config/schema/provider.py#L18-L36)，provider 注册表在 [nomi/providers/factory/registry.py](./nomi/providers/factory/registry.py#L10-L258)。

---

## 工具能力

当前默认会注册这些工具：

- 文件：`read_file`、`write_file`、`edit_file`、`list_dir`
- 搜索：`glob`、`grep`
- 命令：`exec`
- Web：`web_search`、`web_fetch`
- 图片：`analyze_image`
- 定时任务：`cron_create`、`cron_list`、`cron_delete`、`cron_update`
- Skills：`list_skills`、`install_skill`、`uninstall_skill`

默认工具装配在 [nomi/agent/tools/bootstrap.py](./nomi/agent/tools/bootstrap.py#L26-L103)。

---

## 开发与测试

### 运行测试

```bash
uv run python -m pytest -q
```

按模块跑：

```bash
uv run python -m pytest tests/agent -q
uv run python -m pytest tests/cli -q
uv run python -m pytest tests/channels -q
uv run python -m pytest tests/providers -q
uv run python -m pytest tests/tools -q
```

### 语法检查

```bash
uv run python -m compileall nomi tests -q
```

### Ruff

```bash
uv run ruff check nomi tests
```

---

## 项目结构

当前仓库的主结构已经稳定在这几个一级模块：

```text
nomi/
├── agent/       # agent 主循环、上下文、执行、记忆、skills、tools
├── runtime/     # 统一 runtime 装配与生命周期
├── cli/         # 命令入口、交互循环、终端渲染
├── channel/     # 单入口外部 channel 子系统
├── providers/   # provider 解析、注册、后端适配
├── config/      # 配置模型、路径、加载
├── command/     # slash 命令路由与 handlers
├── session/     # 会话持久化
├── cron/        # 应用内调度
├── bus/         # 入站 / 出站消息总线
├── templates/   # prompt 模板和工作区模板
└── utils/       # 通用小工具
```

详细说明见 [docs/README.md](./docs/README.md)。

---

## 文档索引

- [docs/README.md](./docs/README.md)
- [docs/CLI.md](./docs/CLI.md)
- [docs/AGENT.md](./docs/AGENT.md)
- [docs/RUNTIME.md](./docs/RUNTIME.md)
- [docs/WEIXIN.md](./docs/WEIXIN.md)
- [docs/PROVIDERS.md](./docs/PROVIDERS.md)
- [docs/MEMORY.md](./docs/MEMORY.md)

---

## 许可证

[MIT License](./LICENSE)
