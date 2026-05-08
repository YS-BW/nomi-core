# ⚙️ Runtime

`NomiRuntime` 是 CLI 和 channel 共同复用的进程内运行时入口。

它的作用不是“再套一层大框架” 🧱  
而是把真正该统一的东西收口到一起：

- provider 装配 🤖
- bus 创建 📨
- `AgentLoop` 创建 🧠
- transcription provider 创建 🎙️
- 生命周期管理 ♻️

---

## 入口

核心类在 [nomi/runtime/app.py](../nomi/runtime/app.py#L30-L332)。

最重要的入口方法是：

- `NomiRuntime.from_config()`

见 [nomi/runtime/app.py](../nomi/runtime/app.py#L45-L99)。

---

## Runtime 装配了什么

`from_config()` 当前会创建：

- `MessageBus`
- 主 LLM provider
- transcription provider
- `AgentLoop`
- `RuntimeState`
- `RuntimeLifecycle`

装配代码：

- provider build：[nomi/providers/factory/build.py](../nomi/providers/factory/build.py#L10-L72)
- transcription build：[nomi/providers/capabilities/transcription.py](../nomi/providers/capabilities/transcription.py#L183-L199)
- runtime state 绑定：[nomi/runtime/app.py](../nomi/runtime/app.py#L69-L99)

---

## Runtime 对外 API

### 单次调用

```python
await runtime.run_once(...)
```

这会直接走：

```text
NomiRuntime.run_once()
  ↓
AgentLoop.process_direct()
```

对应代码：[nomi/runtime/app.py](../nomi/runtime/app.py#L261-L289)

### 后台启动

```python
await runtime.start()
await runtime.wait()
runtime.stop()
await runtime.close()
```

这些方法统一委托给 `RuntimeLifecycle`：

- `start()`：[nomi/runtime/app.py](../nomi/runtime/app.py#L290-L300)
- `wait()`：[nomi/runtime/app.py](../nomi/runtime/app.py#L301-L310)
- `stop()`：[nomi/runtime/app.py](../nomi/runtime/app.py#L312-L321)
- `close()`：[nomi/runtime/app.py](../nomi/runtime/app.py#L323-L332)

### 控制面 API

Runtime 当前还暴露这些高层控制能力：

- `interrupt_session()`
- `reset_session()`
- `get_status_snapshot()`
- `trigger_dream()`
- `list_cron_jobs()`
- `remove_cron_job()`
- `transcribe_audio()`
- `get_dream_log()`
- `restore_dream_version()`

---

## Runtime 和 CLI 的边界

当前结构里，runtime 已经不再持有 CLI 交互循环。

这点很重要，因为它决定了 runtime 不是“会说话的终端层”，而是“下面真正干活的运行层” 🧱

也就是说：

- `run_interactive_loop()` 在 `nomi/cli/interactive.py`
- `StreamRenderer` 在 `nomi/cli/stream.py`
- `NomiRuntime` 只做进程内运行控制

这是为了避免：

- runtime 反向依赖 CLI
- channel 入口不得不带着 CLI 依赖一起跑

---

## Runtime 和 Channel 的关系

当前 channel 子系统不是“另写一套 runtime”，而是复用 `NomiRuntime`。

链路是：

```text
nomi channel run/start
  ↓
make_runtime(config)
  ↓
NomiRuntime
  ↓
SingleChannelRunner
```

所以：

- CLI 和 channel 共享同一套 agent / session / memory / provider 逻辑
- channel 只是在外层把入站和出站接成微信

---

## Runtime 和语音转写

微信语音入站不直接在微信适配器里自己连模型，而是走 runtime 暴露的统一能力：

```python
await runtime.transcribe_audio(file_path)
```

这样做的好处是：

- channel 不需要知道转写 provider 的配置细节
- 后续别的 channel 也能复用同一个能力

实现见 [nomi/runtime/app.py](../nomi/runtime/app.py#L207-L219)。

---

## Runtime 当前不负责什么

这些事情不属于 runtime：

- prompt_toolkit 交互
- terminal 渲染
- channel service 的 pid / log 管理
- 用户命令解析
- 微信协议实现

这条边界目前是清晰的，文档和代码都应该保持这个事实。
