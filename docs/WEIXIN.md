# 💬 Weixin Channel

Nomi 当前唯一真正跑起来的外部 channel 是微信 📱

它的定位不是“平台抽象演示”，而是真正可跑的个人微信入口。

当前用户可见入口统一是：

```bash
nomi channel ...
```

但内部 active channel kind 目前还是 `weixin`。

---

## 相关代码

### CLI 入口

- channel 命令组：[nomi/cli/commands/channel.py](../nomi/cli/commands/channel.py#L24-L103)

### Service 层

- usecases：[nomi/channel/service/usecases.py](../nomi/channel/service/usecases.py#L1-L19)
- 登录 runtime stub：[nomi/channel/service/login.py](../nomi/channel/service/login.py#L10-L50)
- runtime runner：[nomi/channel/service/runtime.py](../nomi/channel/service/runtime.py#L18-L127)

### 平台实现

- adapter：[nomi/channel/adapters/weixin/channel.py](../nomi/channel/adapters/weixin/channel.py#L142-L837)
- streaming：[nomi/channel/adapters/weixin/streaming.py](../nomi/channel/adapters/weixin/streaming.py#L15-L195)

---

## 配置结构

当前微信配置在：

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

字段定义见 [nomi/config/schema/channel.py](../nomi/config/schema/channel.py#L12-L35)。

### 关键字段

| 字段 | 说明 |
|---|---|
| `channel.kind` | 当前启用的唯一 channel，设成 `weixin` 才会启用 |
| `channel.weixin.allowFrom` | 允许访问的微信用户列表，`"*"` 表示全部 |
| `channel.weixin.baseUrl` | 微信 ilink 服务地址 |
| `channel.weixin.routeTag` | 可选路由标记 |
| `channel.weixin.token` | 可手动注入 token |
| `channel.weixin.stateDir` | 登录态存储目录覆盖 |
| `channel.weixin.pollTimeout` | 长轮询超时时间 |

---

## 登录

### 命令

```bash
nomi channel login
```

### 当前真实行为

这条命令现在不是“如果已有登录态就跳过”，而是固定重新登录 🔁：

1. 清除已有微信状态
2. 清空当前 workspace 下全部 session 文件
3. 请求新的二维码
4. 输出登录链接
5. 如果本机装了 `qrcode`，直接把二维码打印到终端
6. 轮询二维码状态，确认后保存 token

对应代码：

- 打印二维码：[nomi/channel/adapters/weixin/channel.py](../nomi/channel/adapters/weixin/channel.py#L488-L507)
- 二维码轮询登录：[nomi/channel/adapters/weixin/channel.py](../nomi/channel/adapters/weixin/channel.py#L509-L545)
- login 总入口：[nomi/channel/adapters/weixin/channel.py](../nomi/channel/adapters/weixin/channel.py#L547-L571)

### 登录态保存位置

默认保存到：

```text
~/.nomi/weixin/account.json
```

路径解析在 [nomi/channel/registry.py](../nomi/channel/registry.py#L80-L91)。

保存内容除了 `token`，还包括：

- `get_updates_buf`
- `context_tokens`
- `typing_tickets`
- `base_url`

见 [nomi/channel/adapters/weixin/channel.py](../nomi/channel/adapters/weixin/channel.py#L268-L293)。

---

## 启动方式

### 启用与运行

```bash
nomi channel enable weixin
nomi instance restart
```

特点：

- `channel enable` 只修改实例配置
- `instance restart` 启动唯一实例 runtime
- 如果当前没有登录态，runtime 会跳过 weixin adapter 并在状态里显示未运行

命令入口：[nomi/cli/commands/channel.py](../nomi/cli/commands/channel.py#L1-L123)

### 停止与重启

```bash
nomi channel disable
nomi instance restart
```

### 日志

```bash
nomi instance log
```

日志文件：

```text
~/.nomi/logs/runtime-service.log
```

路径定义在 [nomi/runtime/service/state.py](../nomi/runtime/service/state.py#L53-L65)。

---

## 运行规则

当前产品规则：

- 一个 instance root 只允许一个实例 runtime
- weixin 是挂在该 runtime 上的 adapter
- channel 配置变化通过 `nomi instance restart` 生效

统一 runtime 状态在 [nomi/runtime/service/state.py](../nomi/runtime/service/state.py#L1-L306)。

---

## 微信收消息

### 长轮询

微信当前通过 ilink HTTP 长轮询接收消息：

- `getupdates`
- 保存 `get_updates_buf`
- 逐条转成 `InboundMessage`

轮询主逻辑：

- start：[nomi/channel/adapters/weixin/channel.py](../nomi/channel/adapters/weixin/channel.py#L573-L613)
- 单次 poll：[nomi/channel/adapters/weixin/channel.py](../nomi/channel/adapters/weixin/channel.py#L699-L726)

### 当前支持的入站类型

| 类型 | 支持情况 | 处理方式 |
|---|---|---|
| 文本 | 支持 | 直接作为正文 |
| 图片 | 支持 | 下载后作为附件，并补一段提示文本 |
| 文件 | 支持 | 下载后作为附件，并补一段提示文本 |
| 语音 | 支持 | 优先用微信自带文本；没有时下载后走 runtime transcription |
| 视频 | 部分支持 | 只生成“用户发送了视频”的提示文本 |

消息归一化入口在 [nomi/channel/adapters/weixin/channel.py](../nomi/channel/adapters/weixin/channel.py#L727-L837)。

### `allowFrom`

当前只接受 `allowFrom` 允许的发送者：

- `["*"]` 表示全部允许
- 否则必须显式匹配 sender id

见 [nomi/channel/adapters/weixin/channel.py](../nomi/channel/adapters/weixin/channel.py#L683-L697)。

---

## 微信发消息

### 普通最终消息

最终消息通过：

- `send_message()`

发给微信，但它会受流式状态影响，不是所有最终文本都会直接再发一次。

从测试可以看出，当前规则是：

- 如果本轮已经有流式 delta 并已发送，就不会再重复发最终整段
- cron 触发这种场景允许原样发送包含 `<part>` 的最终文本

相关测试：

- [tests/channels/test_weixin.py](../tests/channels/test_weixin.py#L622-L661)
- [tests/channels/test_weixin.py](../tests/channels/test_weixin.py#L665-L695)

### 下行文件

当前微信 channel 已支持 Nomi 主动下发本地文件：

- 入口仍然复用 `OutboundMessage`
- 如果 `message.media` 里带的是本地文件路径，微信 adapter 会先上传文件，再发送 `file_item`
- 如果同时存在 `content`，会先发文件，再按原有逻辑发送文本

当前实现只收口了文件类型，不顺手扩图片/视频下行。

实现路径：

- 先 `getuploadurl`
- 本地按微信协议做 AES-128-ECB 加密上传
- 取响应头 `x-encrypted-param`
- 再通过 `sendmessage` 发送 `file_item`

### typing 状态

当前微信已经支持官方那套 typing：

- 首次流式输出前发 `status=1`
- 活跃流式期间每 5 秒 keepalive 一次
- 收尾时发 `status=2`

关键代码：

- getconfig：[nomi/channel/adapters/weixin/channel.py](../nomi/channel/adapters/weixin/channel.py#L416-L424)
- sendtyping：[nomi/channel/adapters/weixin/channel.py](../nomi/channel/adapters/weixin/channel.py#L438-L466)
- typing keepalive：[nomi/channel/adapters/weixin/streaming.py](../nomi/channel/adapters/weixin/streaming.py#L141-L195)

---

## 分段规则

这是当前微信链路里最关键的一点。

### 当前实现不是“智能切段”

现在微信 channel 不会自己按语义理解后切分。  
它的真实规则是：

- 持续接收 model 输出的流式 delta
- 把可见文本拼到缓冲区
- 只有遇到 `<part>` 时，才把 `<part>` 前面的内容 flush 成一条微信消息
- `_stream_end` 时，如果缓冲区还有非空尾段，就把尾段再发出去
- 连续空段会被跳过

对应实现：

- marker 定义：[nomi/channel/adapters/weixin/streaming.py](../nomi/channel/adapters/weixin/streaming.py#L15-L18)
- 分段 flush：[nomi/channel/adapters/weixin/streaming.py](../nomi/channel/adapters/weixin/streaming.py#L106-L123)
- stream end flush：[nomi/channel/adapters/weixin/streaming.py](../nomi/channel/adapters/weixin/streaming.py#L90-L104)

### 这意味着什么

这意味着：

- 微信分段主要由模型决定
- channel 只是根据 `<part>` 做机械 flush
- 如果模型不给 `<part>`，长文本就一直缓冲到 `_stream_end`

测试已经覆盖了这些事实：

- 只有出现 `<part>` 才发送前面内容：[tests/channels/test_weixin.py](../tests/channels/test_weixin.py#L443-L468)
- 单个 delta 含多个 `<part>` 时会多次 flush：[tests/channels/test_weixin.py](../tests/channels/test_weixin.py#L472-L490)
- 跨 delta 拼出 `<part>` 也能正确 flush：[tests/channels/test_weixin.py](../tests/channels/test_weixin.py#L494-L518)
- 不会因为文本太长就自己硬切：[tests/channels/test_weixin.py](../tests/channels/test_weixin.py#L522-L545)
- stream end 时尾段会发送：[tests/channels/test_weixin.py](../tests/channels/test_weixin.py#L549-L575)

### 模型侧约束

微信 channel 专属 prompt 仍然要求模型：

- 用 `<part>` 作为唯一分段标记
- 每段结尾必须带 `<part>`
- `<part>` 前后不能有空格

模板文件见 [nomi/templates/CHANNEL_WEIXIN.md](../nomi/templates/CHANNEL_WEIXIN.md#L1-L150)。

---

## 工作区与状态文件

微信相关的运行态通常会分布在：

```text
~/.nomi/weixin/account.json
~/.nomi/logs/runtime-service.pid
~/.nomi/logs/runtime-service.json
~/.nomi/logs/runtime-service.log
~/.nomi/media/weixin/
```

路径来源：

- 登录态：[nomi/channel/registry.py](../nomi/channel/registry.py#L80-L91)
- runtime pid/log/state：[nomi/runtime/service/state.py](../nomi/runtime/service/state.py#L53-L65)
- 媒体目录：[nomi/config/paths.py](../nomi/config/paths.py#L26-L29)

---

## 当前限制

当前微信实现有几个边界要明确：

- 用户入口不暴露平台名，只暴露 `nomi channel`
- 当前 active kind 只实现 `weixin`
- `feishu` 只有配置壳，没有运行逻辑
- 微信分段依赖 `<part>`，不是 channel 自己做语义切分
- 外部 channel 全局只允许一个实例占用 runtime
