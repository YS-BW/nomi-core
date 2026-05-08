# 🖥️ Remote

这一层不是微信那种外部聊天平台 channel，  
而是 **给桌面壳 / 远程前端使用的服务端 bridge** 🔌

它的定位很明确：

- Nomi 继续在服务器上跑 `runtime + agent`
- 远程客户端只负责输入、显示、订阅状态
- 协议走 `HTTP + WebSocket`

---

## 当前形态

现在这套 remote 子系统只做服务端，不在主仓直接实现完整桌宠 UI。

已经落地的能力：

- `nomi remote run`
- `nomi remote start`
- `nomi remote stop`
- `nomi remote restart`
- `nomi remote log`
- WebSocket 双向命令/事件协议
- 复用当前 `session / memory / tasks / interrupt`
- 与微信 channel 并存，不抢占它的 outbound 消费

正式桌面端现在已经独立到 `nomi-desktop` 仓库：

- `Tauri + React`
- 默认 `desktop:{clientId}` session
- 复用当前 remote 协议，不新增第二套桌面专用后端
- 共享协议基线已经独立到 `nomi-protocol` 仓，并通过外部依赖接入 core / desktop

---

## 启动方式

配置示例：

```json
{
  "remote": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 8765,
    "authToken": "your-token"
  }
}
```

启动：

```bash
nomi remote run
```

后台启动：

```bash
nomi remote start
nomi remote log
```

---

## 协议

当前共享协议 owner 已经固定为：

- Python 基线 spec：
  - 当前位于独立 `nomi-protocol` 仓
- Python 薄封装：
  - 当前通过安装的 `nomi-protocol` 包提供
- desktop 薄封装：
  - 当前位于独立 `nomi-desktop` 仓，由 `nomi-protocol` npm 包提供

当前这一步已经完成物理拆仓，后续协议升级通过 `nomi-protocol` tag 推进。

WebSocket 地址：

```text
ws://127.0.0.1:8765/ws
```

请求头：

```text
Authorization: Bearer <remote.auth_token>
```

浏览器最小验证器额外支持：

```text
ws://127.0.0.1:8765/ws?token=<remote.auth_token>
```

原因很直接：

- 浏览器原生 WebSocket 不能自定义 `Authorization` header
- 所以 demo 走 query token
- 正式桌面壳 / 非浏览器客户端仍然优先走 Bearer Token

最小 HTTP 健康检查：

```text
GET /health
```

Skill zip 上传：

```text
POST /skills/upload
Authorization: Bearer <remote.auth_token>
```

上传成功后会返回 `upload_token`，再通过 WebSocket `skill_install` 完成真正安装。

---

## 命令

- 聊天与历史：
  - `bind_session`
  - `send_message`
  - `interrupt_turn`
  - `get_status`
  - `list_sessions`
  - `load_history`
  - `get_sidebar`
- 任务管理：
  - `task_create_after`
  - `task_create_at`
  - `task_create_daily`
  - `task_create_every`
  - `task_delete`
  - `task_enable`
  - `task_disable`
  - `task_update_instruction`
  - `task_reschedule_after`
  - `task_reschedule_at`
  - `task_reschedule_daily`
  - `task_reschedule_every`
- Skill 管理：
  - `skill_install`
  - `skill_uninstall`
- MCP 管理：
  - `mcp_create`
  - `mcp_update`
  - `mcp_delete`
  - `mcp_enable`
  - `mcp_disable`
- 运行态管理：
  - `clear_remote_runtime`

---

## 事件

- `ready`
- `session_bound`
- `turn_started`
- `progress`
- `delta`
- `stream_end`
- `message`
- `turn_completed`
- `interrupt_result`
- `status_result`
- `history_snapshot`
- `session_list`
- `task_delivered`
- `sidebar_snapshot`
- `resource_action_result`
- `error`

---

## 最小网页验证器

仓库现在自带一个最小 remote client demo：`examples/remote-client/` 🧪

启动方式：

```bash
nomi remote run
uv run python -m http.server 8080 -d examples/remote-client
```

然后浏览器打开：

```text
http://127.0.0.1:8080
```

这个 demo 当前用来验证：

- 连接 `ws://.../ws`
- 绑定 session
- 发送消息并接收流式 `delta`
- 中断当前轮
- 加载历史
- 接收 `task_delivered`

---

## 正式 Desktop Shell

正式桌面端现在位于独立 `nomi-desktop` 仓。

当前 `nomi-core` 只记录和桌面端对接直接相关的事实：

- remote 继续作为服务端 bridge
- 协议 owner 继续是独立 `nomi-protocol` 仓
- desktop 通过 `bind_session / send_message / load_history / get_sidebar` 接入
- skill zip 上传仍由 `POST /skills/upload` 提供

---

## 事件时序示例

一轮正常聊天的典型事件顺序：

```text
send_message
  -> turn_started
  -> delta*
  -> stream_end*
  -> message
  -> turn_completed
```

说明：

- `delta` 是用户可见正文增量
- `stream_end` 只是流式片段结束
- `message` 是最终可见文本
- `turn_completed` 才表示这一轮真正收尾

---

## 代码入口

- Remote server：[nomi/remote/server.py](../nomi/remote/server.py#L1-L483)
- Remote bridge：[nomi/remote/bridge.py](../nomi/remote/bridge.py#L1-L93)
- Hub：[nomi/remote/hub.py](../nomi/remote/hub.py#L1-L61)
- CLI 命令：[nomi/cli/commands/remote.py](../nomi/cli/commands/remote.py#L1-L78)
- Runtime facade：[nomi/runtime/app.py](../nomi/runtime/app.py#L230-L748)
- Demo client：[examples/remote-client/app.js](../examples/remote-client/app.js#L1-L410)
