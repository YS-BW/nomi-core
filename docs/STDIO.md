# 📡 Runtime Protocol

这份文档只说明当前还保留在代码里的 runtime 协议辅助层 📡

先说结论：

- 当前用户可见 CLI 不暴露 `nomi stdio` 🚫
- 也不暴露旧的 `serve stdio`
- 但 runtime 里仍然保留了协议构造函数

所以这部分现在更适合被理解成：

> 内部可复用的协议 helper，而不是正式产品入口。

---

## 代码位置

- 协议 helper：[nomi/runtime/protocol.py](../nomi/runtime/protocol.py#L12-L99)

---

## 当前协议事件

### session key

默认 session key 规则：

- [nomi/runtime/protocol.py](../nomi/runtime/protocol.py#L12-L15)

### ready

```json
{"type":"ready"}
```

构造函数：

- [nomi/runtime/protocol.py](../nomi/runtime/protocol.py#L17-L20)

### progress

```json
{
  "type": "progress",
  "session_id": "cli:direct",
  "content": "...",
  "tool_hint": false
}
```

构造函数：

- [nomi/runtime/protocol.py](../nomi/runtime/protocol.py#L22-L35)

### delta

```json
{
  "type": "delta",
  "session_id": "cli:direct",
  "content": "..."
}
```

构造函数：

- [nomi/runtime/protocol.py](../nomi/runtime/protocol.py#L37-L44)

### stream_end

```json
{
  "type": "stream_end",
  "session_id": "cli:direct",
  "resuming": false
}
```

构造函数：

- [nomi/runtime/protocol.py](../nomi/runtime/protocol.py#L46-L53)

### message

最终完整消息事件：

- [nomi/runtime/protocol.py](../nomi/runtime/protocol.py#L55-L68)

### error

- [nomi/runtime/protocol.py](../nomi/runtime/protocol.py#L71-L76)

### interrupt_result

- [nomi/runtime/protocol.py](../nomi/runtime/protocol.py#L79-L85)

### reset_done

- [nomi/runtime/protocol.py](../nomi/runtime/protocol.py#L88-L90)

### status_result

- [nomi/runtime/protocol.py](../nomi/runtime/protocol.py#L93-L99)

---

## 当前定位

如果以后需要重新暴露脚本化入口，这层协议 helper 可以继续复用。

但在当前版本里，这部分不能被文档写成“正式可用命令面”，否则就会和当前 CLI 事实冲突。
