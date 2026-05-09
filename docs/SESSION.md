# 💬 Session

Session 是 Nomi 当前“短期对话上下文”的持久化层 💬

它不是长期记忆仓库，而更像“这条对话线程的聊天记录本” 📒

它的作用主要是：

- 保存当前会话的完整消息链
- 在下一轮对话时恢复上下文
- 配合 consolidator 做归档边界管理
- 保存运行态 checkpoint

---

## 代码位置

- session 模型和 manager：[nomi/session/manager.py](../nomi/session/manager.py#L15-L219)
- runtime checkpoint 写回由 `TurnProcessor` 接入：[nomi/agent/execution/processor.py](../nomi/agent/execution/processor.py)

---

## 存储格式

当前 session 保存在：

```text
~/.nomi/workspace/sessions/*.jsonl
```

格式是 JSONL：

1. 第一行 metadata
2. 后面每行一条消息

示意：

```jsonl
{"_type":"metadata","key":"cli:direct","created_at":"...","updated_at":"...","metadata":{},"last_consolidated":0}
{"role":"user","content":"你好","timestamp":"..."}
{"role":"assistant","content":"你好，我在。","timestamp":"..."}
```

写回逻辑在 [nomi/session/manager.py](../nomi/session/manager.py#L174-L191)。

---

## Session 模型

`Session` 当前包含：

- `key`
- `messages`
- `created_at`
- `updated_at`
- `metadata`
- `last_consolidated`

定义见 [nomi/session/manager.py](../nomi/session/manager.py#L15-L24)。

---

## 会话历史读取规则

`Session.get_history()` 不是简单把所有消息原样返回，它会做几层清洗：

1. 只取未归档部分
2. 如果超限，只保留最近消息
3. 尽量从用户消息开始，避免截断在半个轮次中间
4. 去掉开头不合法的孤儿 tool 结果
5. 只保留适合送回模型的字段

见 [nomi/session/manager.py](../nomi/session/manager.py#L37-L63)。

---

## `last_consolidated`

这个字段表示：

- `messages` 里前多少条已经被归档到长期历史

因此：

- system prompt / 历史恢复时不会把那部分再重复塞进去
- consolidator 能知道哪些内容已经沉淀

---

## `/new` 时发生什么

当用户执行 `/new`：

1. 当前 session 的未归档消息会被截取出来
2. session 清空
3. metadata 也按需清掉
4. 旧消息交给 consolidator 后台归档

对应：

- [nomi/agent/loop.py](../nomi/agent/loop.py#L244-L253)

---

## 会话 key

默认规则来自 `InboundMessage.session_key`：

- [nomi/bus/events.py](../nomi/bus/events.py#L21-L25)

常见形式：

- `cli:direct`
- `weixin:<chat_id>`

如果是 unified session 模式，会被 `AgentLoop` 归一化成：

- `unified:default`

---

## 会话写回时的清洗

不是所有发送给模型的内容都会原样落到 session 文件。

例如：

- runtime context block 不应该原样持久化
- data URL 图片不应该直接持久化到 session
- 超长 tool result 会被截断

这些清洗逻辑在 [nomi/agent/execution/processor.py](../nomi/agent/execution/processor.py#L484-L560)。

---

## Remote 会话管理

当前 core 已经把 remote 的会话语义收口成显式管理：

- `SessionManager.create_session()` 会立刻写入一份空 session 文件
- `SessionManager.delete_session()` 会同时移除磁盘文件和内存缓存
- `SessionManager.list_sessions()` 现在会返回 remote 可直接消费的摘要字段：
  - `session_id`
  - `title`
  - `created_at_ms`
  - `updated_at_ms`
  - `message_count`
  - `archived`
  - `source`
- remote facade 在读取历史、取状态、发送消息、中断前会先检查 session 是否存在；不存在就直接报 `session_not_found`，不会再隐式创建空会话

相关代码：

- Session manager：[nomi/session/manager.py](../nomi/session/manager.py#L109-L331)
- Remote facade：[nomi/runtime/app.py](../nomi/runtime/app.py#L305-L439)

---

## 当前边界

session 层当前只管：

- 会话结构
- JSONL 持久化
- 缓存与加载

它不负责：

- 长期记忆整理
- 画像候选抽取
- channel 协议

这层越薄，越容易稳定。
