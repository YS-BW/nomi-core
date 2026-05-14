# 🤖 Providers

Nomi 的 provider 子系统，简单理解就是“模型接入层” 🤖

当前整体分成三层：

1. 配置结构
2. provider 解析
3. backend 实例化

---

## 配置结构

配置模型定义在 [nomi/config/schema/provider.py](../nomi/config/schema/provider.py#L10-L36)。

当前实际存在的 provider 配置段是：

- `custom`
- `deepseek`
- `qwen`
- `minimax`
- `mimo`
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

每个 provider 配置结构都很薄：

```json
{
  "apiKey": "",
  "apiBase": null,
  "extraHeaders": null
}
```

---

## 默认值

当前默认 agent provider 配置在 [nomi/config/schema/agent.py](../nomi/config/schema/agent.py#L20-L38)：

- `provider = "custom"`
- `model = "mimo-v2.5"`
- `contextWindowTokens = 65536`
- `temperature = 0.1`

这意味着：

- 首次默认走 `custom` 🧩
- 但模型名默认就是小米 `mimo-v2.5` 🍚
- 实际上相当于“默认使用一个 OpenAI 兼容端点去接 Mimo”

---

## Provider 注册表

当前 provider 元数据注册表在：

- [nomi/providers/factory/registry.py](../nomi/providers/factory/registry.py#L10-L257)

注册表里定义了每个 provider 的：

- `name`
- `display_name`
- `backend`
- `env_key`
- `default_api_base`
- 是否是网关
- 是否是本地 provider
- 是否要 strip model prefix

这张表是整个 provider 体系的事实来源。

---

## 解析逻辑

provider 解析逻辑在：

- [nomi/providers/factory/resolution.py](../nomi/providers/factory/resolution.py#L11-L150)

### 当前解析顺序

大致顺序是：

1. 如果模型名本身带 provider 前缀，优先按前缀解析
2. 如果 `agents.defaults.provider != "auto"`，强制使用这个 provider
3. 如果是 `auto`，按模型关键字匹配
4. 再按本地 provider 的 `api_base` 识别
5. 最后按有 key 的 provider 兜底

这意味着当前行为不是“单靠模型名猜”，而是有一套稳定优先级。

---

## Backend 层

当前 backend 基座仍然主要是三类：

- `openai_compat`
- `anthropic`
- `azure_openai`

但在这三类之上，已经有若干 provider 级轻量 adapter：

- `DeepSeekProvider`
- `QwenProvider`
- `ZhipuProvider`
- `MoonshotProvider`
- `SiliconFlowProvider`
- `MiMoProvider`

对应文件：

- OpenAI 兼容：[nomi/providers/backends/openai_compat.py](../nomi/providers/backends/openai_compat.py)
- Anthropic：[nomi/providers/backends/anthropic.py](../nomi/providers/backends/anthropic.py)
- Azure OpenAI：[nomi/providers/backends/azure_openai.py](../nomi/providers/backends/azure_openai.py)

实例化入口在 [nomi/providers/factory/build.py](../nomi/providers/factory/build.py#L10-L72)。

---

## 哪些是“只是 OpenAI 兼容配置”

这一节可以直接粗暴理解成：

> 很多 provider 名字看起来不一样，但代码里其实走的是同一套 `openai_compat` 后端。🔁

这一点很重要。

当前很多 provider 其实没有单独写一套专有 backend，它们只是：

- 在配置层单独有一个名字
- 在注册表里补了 `default_api_base` 或路由元数据
- 最终还是走 `OpenAICompatProvider`

这类包括：

- `custom`
- `openai`
- `openrouter`
- `vllm`
- `ollama`
- `ovms`
- `aihubmix`
- `volcengine`
- `volcengine_coding_plan`
- `byteplus`
- `byteplus_coding_plan`

真正不是 generic `openai_compat` 的只有：

- `deepseek`
- `qwen`
- `zhipu`
- `moonshot`
- `siliconflow`
- `minimax`
- `mimo`
- `anthropic`
- `azure_openai`

这个事实来自注册表里的 `backend` 字段：

- [nomi/providers/factory/registry.py](../nomi/providers/factory/registry.py#L26-L45)

---

## 当前推荐理解方式

可以把 provider 分成四类去理解：

### 1. 直连自定义兼容端点

- `custom`

你自己填：

- `apiKey`
- `apiBase`

默认的 Mimo 就是这一路。

### 2. 标准官方 / 准官方兼容端点

- `openai`
- `zhipu`

### 3. 网关型 provider

- `openrouter`
- `aihubmix`
- `siliconflow`
- `volcengine`
- `volcengine_coding_plan`
- `byteplus`
- `byteplus_coding_plan`

### 4. 本地 OpenAI 兼容服务

- `vllm`
- `ollama`
- `ovms`

---

## DeepSeek 专用接入

DeepSeek 现在不再建议通过 `custom` 伪装接入。

当前已经有独立的 `deepseek` provider：

- 配置段：`providers.deepseek`
- 默认地址：`https://api.deepseek.com`
- backend：`DeepSeekProvider`

因此常规配置只需要填 `apiKey`：

```json
{
  "agents": {
    "defaults": {
      "provider": "deepseek",
      "model": "deepseek-v4-flash"
    }
  },
  "providers": {
    "deepseek": {
      "apiKey": "你的 key"
    }
  }
}
```

如果你填了 `apiBase`，会覆盖默认官方地址；否则直接走官方默认地址。

之所以单独做 `deepseek` backend，而不是继续复用 generic `custom`，是因为 DeepSeek 在 thinking mode 下的多轮 tool-call transcript 回放语义和普通 OpenAI 兼容端点不同，尤其是：

- assistant tool-call 消息的空 `content` 不能被改写成 `null`
- `deepseek-reasoner` 不适合走当前工具调用链路

对应实现入口：

- [nomi/providers/backends/deepseek.py](../nomi/providers/backends/deepseek.py#L1-L179)
- [nomi/providers/factory/build.py](../nomi/providers/factory/build.py#L10-L81)

### DeepSeek 模型建议

当前推荐：

- 带工具调用：`deepseek-v4-flash` 或 `deepseek-v4-pro`
- 纯推理文本：`deepseek-reasoner`

当前代码事实：

- `deepseek-v4-*` 在带工具时优先走非流式请求，再把最终文本回灌到 CLI 渲染
- `deepseek-reasoner` 如果带 tools，会直接返回明确错误，不再把 DeepSeek 的 400 原样漏给用户

## Qwen 正式接入

阿里百炼 Qwen 当前推荐通过独立 `qwen` provider 接入，而不是继续走 `custom` 伪装。

当前代码事实：

- 配置段：`providers.qwen`
- 默认地址：`https://dashscope.aliyuncs.com/compatible-mode/v1`
- backend：`QwenProvider`

因此常规配置只需要填 `apiKey`：

```json
{
  "agents": {
    "defaults": {
      "provider": "qwen",
      "model": "qwen-max"
    }
  },
  "providers": {
    "qwen": {
      "apiKey": "你的 key"
    }
  }
}
```

如果你填了 `apiBase`，会覆盖默认官方地址；否则直接走官方默认地址。

当前不建议再用 `custom + apiBase` 伪装配置 Qwen。原因不是“不能用”，而是 Qwen 有专门的 thinking 请求参数，需要通过 `QwenProvider` 统一处理：

- `enable_thinking`
- `preserve_thinking`
- 强制 `tool_choice` 时自动关闭 thinking

### Qwen 模型建议

当前内置目录优先覆盖：

- `qwen-max`
- `qwen-plus`
- `qwen-turbo`
- `qwen3-235b-a22b`
- `qwen3-32b`
- `qwen3-14b`
- `qwen3-8b`

带工具调用时，v1 推荐优先使用 `qwen-max`。

## Zhipu 正式接入

智谱当前继续走 OpenAI Chat Completions 兼容接口，但不再只是 generic `openai_compat` 配置。

当前代码事实：

- 配置段：`providers.zhipu`
- 默认地址：`https://open.bigmodel.cn/api/paas/v4`
- backend：`ZhipuProvider`

因此常规配置仍然只需要填 `apiKey`：

```json
{
  "agents": {
    "defaults": {
      "provider": "zhipu",
      "model": "glm-4.5"
    }
  },
  "providers": {
    "zhipu": {
      "apiKey": "你的 key"
    }
  }
}
```

当前不建议再把智谱只当成“普通 OpenAI 兼容端点”理解。原因不是响应结构不同，而是它的 thinking 和工具选择参数需要 provider 层单独收口：

- `extra_body.thinking`
- preserved thinking 时自动带 `clear_thinking: false`
- 强制 `tool_choice` 时自动降级成 `auto`

## MiniMax 正式接入

MiniMax 当前推荐通过独立 `minimax` provider 接入，而不是继续走 `custom` 伪装。

当前代码事实：

- 配置段：`providers.minimax`
- 默认地址：`https://api.minimaxi.com/anthropic`
- backend：复用 `AnthropicProvider`

因此常规配置只需要填 `apiKey`：

```json
{
  "agents": {
    "defaults": {
      "provider": "minimax",
      "model": "MiniMax-M2.7"
    }
  },
  "providers": {
    "minimax": {
      "apiKey": "你的 key"
    }
  }
}
```

如果你填了 `apiBase`，会覆盖默认官方地址；否则直接走官方默认地址。

当前不建议再用 `custom + apiBase` 伪装配置 MiniMax。原因不是“不能用”，而是当前官方推荐的 tool calling / interleaved thinking 路径更接近 Anthropic block 语义，复用现有 `AnthropicProvider` 更稳。

### MiniMax 模型建议

当前内置目录优先覆盖：

- `MiniMax-M2.7`
- `MiniMax-M2.7-highspeed`
- `MiniMax-M2.5`
- `MiniMax-M2.5-highspeed`
- `MiniMax-M2.1`
- `MiniMax-M2.1-highspeed`
- `MiniMax-M2`

带工具调用时，当前推荐优先使用 `MiniMax-M2.7`。

## Moonshot / Kimi 正式接入

Moonshot 当前继续走 OpenAI Chat Completions 兼容接口，但也不再只是 generic `openai_compat` 配置。

当前代码事实：

- 配置段：`providers.moonshot`
- 默认地址：`https://api.moonshot.cn/v1`
- backend：`MoonshotProvider`

因此常规配置只需要填 `apiKey`：

```json
{
  "agents": {
    "defaults": {
      "provider": "moonshot",
      "model": "kimi-k2.6"
    }
  },
  "providers": {
    "moonshot": {
      "apiKey": "你的 key"
    }
  }
}
```

如果你填了 `apiBase`，会覆盖默认官方地址；否则直接走官方默认地址。

当前不建议再把 Kimi 只当成“普通 OpenAI 兼容端点”理解。原因不是响应结构完全不同，而是它有几条需要 provider 层单独收口的官方约束：

- `kimi-k2.6 / kimi-k2.5` 的 thinking 通过 `extra_body.thinking` 控制
- 历史里已有 `reasoning_content` 时，当前会补 `thinking.keep = "all"`
- 强制 `tool_choice` 当前固定自动降级成 `auto`
- `kimi-k2.6 / kimi-k2.5 / kimi-k2-thinking*` 当前固定补 `temperature = 1.0`

### Moonshot / Kimi 模型建议

当前内置目录优先覆盖：

- `kimi-k2.6`
- `kimi-k2.5`
- `kimi-k2-thinking`
- `kimi-k2-thinking-preview`
- `kimi-k2-turbo-preview`

带工具调用时，当前推荐优先使用 `kimi-k2.6`。

## SiliconFlow 正式接入

SiliconFlow 当前继续走 OpenAI Chat Completions 兼容接口，但也不再只是 generic `openai_compat` 网关配置。

当前代码事实：

- 配置段：`providers.siliconflow`
- 默认地址：`https://api.siliconflow.cn/v1`
- backend：`SiliconFlowProvider`

因此常规配置只需要填 `apiKey`：

```json
{
  "agents": {
    "defaults": {
      "provider": "siliconflow",
      "model": "Pro/zai-org/GLM-4.7"
    }
  },
  "providers": {
    "siliconflow": {
      "apiKey": "你的 key"
    }
  }
}
```

如果你填了 `apiBase`，会覆盖默认官方地址；否则直接走官方默认地址。

当前不建议再把 SiliconFlow 只当成“普通 OpenAI 兼容网关”理解。原因不是主响应结构不同，而是它有一组需要 provider 层统一收口的官方 thinking 参数：

- `extra_body.enable_thinking`
- `extra_body.thinking_budget`
- reasoning 返回继续复用现有 `reasoning_content` 解析链路

### SiliconFlow 模型建议

当前内置目录优先覆盖：

- `Pro/deepseek-ai/DeepSeek-V3.2`
- `Pro/deepseek-ai/DeepSeek-R1`
- `Pro/Qwen/Qwen3-32B`
- `Pro/zai-org/GLM-4.7`

带工具调用时，当前推荐优先使用 `Pro/zai-org/GLM-4.7`。

## Mimo 默认配置

当前推荐的小米 Mimo 配置方式是直接使用 `mimo` provider。常规 API 只需要填写 `apiKey`，`apiBase` 为空时会回退到默认地址：

- 常规 OpenAI 兼容地址：`https://api.xiaomimimo.com/v1`
- Anthropic 兼容地址：`https://api.xiaomimimo.com/anthropic`

`nomi-core` 当前 `mimo` backend 使用 OpenAI Chat Completions 兼容接口，默认模型仍是 `mimo-v2.5`。

```json
{
  "agents": {
    "defaults": {
      "provider": "mimo",
      "model": "mimo-v2.5"
    }
  },
  "providers": {
    "mimo": {
      "apiKey": "你的常规 API key",
      "apiBase": null
    }
  }
}
```

如果使用 Mimo Token Plan，不要改成 `custom` provider，也不要覆盖常规 `apiBase`。直接填写 `mimo` 下的 Token Plan 专用字段：

```json
{
  "providers": {
    "mimo": {
      "apiKey": "",
      "apiBase": null,
      "tokenPlanApiKey": "tp-xxxxx",
      "tokenPlanApiBase": "https://token-plan-cn.xiaomimimo.com/v1"
    }
  }
}
```

Token Plan 的 base URL 以订阅页面显示为准，官方当前文档列出的 OpenAI 兼容地址包括：

- `https://token-plan-cn.xiaomimimo.com/v1`
- `https://token-plan-sgp.xiaomimimo.com/v1`
- `https://token-plan-ams.xiaomimimo.com/v1`

当 `tokenPlanApiKey` 存在时，`mimo` backend 会优先使用 Token Plan key；当 `tokenPlanApiBase` 存在时，会优先使用 Token Plan base URL。

Mimo 官方文档还明确要求：在 thinking 模式开启且多轮工具调用历史里存在 assistant `reasoning_content` 时，后续轮次必须完整回传相关 `reasoning_content`，否则可能返回 400。当前 `nomi-core` 会保存并回放 provider 返回的 `reasoning_content`，不要在 session 或 transcript 清洗逻辑里丢掉该字段。

---

## Model Catalog

当前内置 model catalog 不覆盖所有 provider，只覆盖少数稳定条目，用来给向导补全和推荐上下文窗口。

当前目录文件：

- [nomi/providers/factory/model_catalog.py](../nomi/providers/factory/model_catalog.py#L10-L217)

当前内置条目主要覆盖：

- `qwen` -> `qwen-max` / `qwen-plus` / `qwen3-*`
- `zhipu` -> 仍以当前用户自配模型为主，provider 层负责请求参数收口
- `minimax` -> `MiniMax-M2.7` / `MiniMax-M2.5` / `MiniMax-M2.1`
- `custom` -> `mimo-v2.5`
- `openai` -> `gpt-5` / `gpt-5-mini` / `gpt-4.1` / `gpt-4.1-mini`
- `anthropic` -> Claude 4 / Claude 3.7
- `moonshot` -> `kimi-k2.6` / `kimi-k2-thinking` 等
- `siliconflow` -> `Pro/zai-org/GLM-4.7` / `Pro/deepseek-ai/DeepSeek-V3.2` 等

这个目录现在主要服务：

- onboard 向导建议
- context window 自动推荐

---

## 转写 Provider

语音转写不走主 provider 注册表，而是单独有一个 capability：

- [nomi/providers/capabilities/transcription.py](../nomi/providers/capabilities/transcription.py#L96-L199)

当前只实现：

- DashScope `qwen3-asr-flash`

配置结构：

```json
{
  "transcription": {
    "apiKey": "...",
    "apiBase": "https://dashscope.aliyuncs.com/compatible-mode/v1"
  }
}
```

---

## 当前边界

provider 子系统当前要保持的边界是：

- `config/schema/provider.py` 只管配置模型
- `factory/registry.py` 只管元数据
- `factory/resolution.py` 只管解析路由
- `factory/build.py` 只管实例化
- `backends/*` 只管实际 API 协议实现

如果把这些再糊回一个大文件，后面会很难维护。
