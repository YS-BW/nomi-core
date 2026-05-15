# 🤖 Providers

Provider 是 Nomi 接入模型的方式。它负责把统一的 Agent 请求转换成具体模型厂商或网关能理解的请求。

简单说：用户选择 provider 和 model，Nomi 用它来完成对话、工具调用和任务执行。

## 🌟 当前支持什么

当前注册表里包含多种 provider：

- Custom OpenAI-compatible
- DeepSeek
- Qwen
- MiniMax
- MiMo
- Azure OpenAI
- Anthropic
- OpenAI
- OpenRouter
- Zhipu
- vLLM
- Ollama
- OVMS
- Moonshot
- AiHubMix
- SiliconFlow
- VolcEngine
- BytePlus

其中有些是独立 backend，有些是 OpenAI 兼容网关。

## ⚙️ 配置方式

核心配置在：

```text
<instance-root>/config.json
```

常见字段：

```json
{
  "agents": {
    "defaults": {
      "provider": "deepseek",
      "model": "deepseek-chat"
    }
  },
  "providers": {
    "deepseek": {
      "apiKey": "sk-..."
    }
  }
}
```

配置改完后，后台实例需要 reload 或 restart。

## 🌐 Custom Provider

`custom` 用于接入 OpenAI 兼容接口。

它适合：

- 自建模型网关。
- 私有部署。
- 临时接入不在注册表里的兼容服务。

`custom` 是当前唯一允许用户编辑 `apiBase` 的 provider。

## 🔁 Provider Reload

通过 remote 或 CLI 更新 provider 配置后，可以触发 runtime reload。

reload 后，同一实例中的：

- desktop 对话
- 微信对话
- 自动任务
- instance 消息

都会使用新的 provider。

## 🔐 API Key

API key 存在实例配置里。remote provider state 会告诉前端 key 是否已设置和预览，但不应该把完整 key 当普通状态随便暴露。

## 🧱 边界

- provider 只负责模型请求，不负责工具权限。
- 工具权限由 ToolRegistry / runtime / instance permission 控制。
- 非 custom provider 的默认 base URL 由注册表管理。
- 本地 provider 例如 Ollama/vLLM 可以不需要传统 API key。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/config/schema/provider.py](../nomi/config/schema/provider.py#L10-L58) | provider 配置模型 |
| [nomi/config/schema/agent.py](../nomi/config/schema/agent.py#L20-L43) | 默认 provider/model 配置 |
| [nomi/providers/factory/registry.py](../nomi/providers/factory/registry.py#L11-L180) | provider 注册表 |
| [nomi/providers/factory/resolution.py](../nomi/providers/factory/resolution.py#L1-L199) | provider 解析 |
| [nomi/providers/factory/build.py](../nomi/providers/factory/build.py#L10-L159) | provider 实例化 |
| [nomi/providers/base.py](../nomi/providers/base.py#L1-L120) | provider 基础接口 |
| [nomi/runtime/app.py](../nomi/runtime/app.py#L2009-L2035) | runtime reload |
