# 📡 Runtime Protocol Helper

`STDIO.md` 记录的是当前代码里仍保留的 runtime 协议 helper。

它不是当前用户可见入口。现在没有正式暴露 `nomi stdio` 或旧的 `serve stdio` 主流程。

## 🌟 它现在是什么

当前这部分更适合理解为内部 helper：

- 构造默认 session id。
- 构造 ready/progress/delta/final/error 等事件 payload。
- 给当前仍依赖 runtime protocol payload 的内部代码和测试复用。

## 🚫 它不是什么

它不是：

- 正式 CLI 命令。
- desktop remote 协议。
- 当前 channel 协议。
- 新集成方式。

desktop 当前走的是 remote HTTP + SSE，见 [REMOTE.md](./REMOTE.md)。

## 🧱 使用边界

- 不要把这里写成正式产品入口。
- 它只作为内部 helper 维护，不承担兼容入口职责。
- remote 协议能力由 `nomi-protocol` 维护，不能在这里私自扩展 desktop 接口。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/runtime/protocol.py](../nomi/runtime/protocol.py#L1-L8) | runtime 协议 helper |
| [nomi/remote/server.py](../nomi/remote/server.py#L69-L186) | 当前正式 remote HTTP + SSE 服务 |
