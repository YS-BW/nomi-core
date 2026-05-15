# 💬 Session

Session 是 Nomi 的对话历史。每个入口、每个聊天对象、每个 instance 关系都会形成自己的会话 key，并保存成 JSONL 文件。

它不是长期记忆，而是当前对话线程的短期上下文。

## 🌟 Session 用来做什么

Session 负责：

- 保存用户消息和 assistant 回复。
- 保存工具调用相关消息。
- 为下一轮对话提供历史上下文。
- 支持 desktop 侧读取会话列表和消息。
- 支持 instance 会话查询。
- 保存运行态 checkpoint 和中断恢复信息。

## 🔑 会话 Key

常见会话 key：

| 来源 | 示例 |
|---|---|
| CLI | `cli:direct` |
| Remote / Desktop | `remote:<id>` |
| 微信 | `weixin:<chat_id>` |
| Instance | `instance:<relation_key>` |
| 自动任务内部执行 | `task:<task_id>:run` |

会话 key 决定消息写入哪个历史文件。

## 📄 存储格式

Session 保存在：

```text
<instance-root>/sessions/*.jsonl
```

文件格式是 JSONL：

```jsonl
{"_type":"metadata","key":"cli:direct","created_at":"...","updated_at":"...","metadata":{},"last_consolidated":0}
{"role":"user","content":"你好","timestamp":"..."}
{"role":"assistant","content":"你好，我在。","timestamp":"..."}
```

第一行是 metadata，其余每行是一条消息。

## 🧠 和长期记忆的关系

Session 是短期对话历史。
长期记忆在 workspace 的 `memory/` 和 `USER.md` 中。

当会话变长时，consolidator / auto compact 会参与整理，避免每轮都把无限历史塞进模型。

## 🤝 Instance 会话

两个 Nomi 实例聊天时，本地会写入：

```text
instance:<key>
```

同一个 relation key 只对应一个 instance session。用户问“你刚才和哪个 Nomi 聊了什么”时，模型会使用 `instance_session_list` 和 `instance_session_get` 查询这里。

## 🧱 边界

- Session 不是事实数据库，只是对话历史。
- 删除 session 会丢掉这条对话线程的短期上下文。
- `USER.md` 这类长期画像不会因为清 session 自动删除。
- instance relation 删除后，历史 session 仍可能存在，但关系状态会显示 unknown。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/session/manager.py](../nomi/session/manager.py#L18-L111) | Session 数据模型 |
| [nomi/session/manager.py](../nomi/session/manager.py#L112-L240) | SessionManager 读取、创建、删除 |
| [nomi/session/manager.py](../nomi/session/manager.py#L241-L381) | JSONL 落盘、列表和订阅 |
| [nomi/agent/execution/processor.py](../nomi/agent/execution/processor.py#L339-L530) | 单轮消息写入 session |
| [nomi/runtime/app.py](../nomi/runtime/app.py#L1953-L1971) | remote sidebar/session 序列化 |
| [nomi/agent/tools/instance_relations.py](../nomi/agent/tools/instance_relations.py#L314-L408) | instance session 查询工具 |
