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

当前 backend 只分三类：

- `openai_compat`
- `anthropic`
- `azure_openai`

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

真正不是 `openai_compat` 的只有：

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
- `moonshot`

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

## Mimo 默认配置

当前默认推荐的小米 Mimo 配置方式就是：

```json
{
  "agents": {
    "defaults": {
      "provider": "custom",
      "model": "mimo-v2.5"
    }
  },
  "providers": {
    "custom": {
      "apiKey": "你的 key",
      "apiBase": "https://token-plan-cn.xiaomimimo.com/v1"
    }
  }
}
```

这也是你本机当前 `~/.nomi/config.json` 的实际结构。

---

## Model Catalog

当前内置 model catalog 不覆盖所有 provider，只覆盖少数稳定条目，用来给向导补全和推荐上下文窗口。

当前目录文件：

- [nomi/providers/factory/model_catalog.py](../nomi/providers/factory/model_catalog.py#L10-L217)

当前内置条目主要覆盖：

- `custom` -> `mimo-v2.5`
- `openai` -> `gpt-5` / `gpt-5-mini` / `gpt-4.1` / `gpt-4.1-mini`
- `anthropic` -> Claude 4 / Claude 3.7
- `moonshot` -> `kimi-k2.5` 等

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
