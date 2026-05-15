# 📁 Workspace

Workspace 是某个 instance 的工作区。它保存 Nomi 的启动文件、长期记忆和部分工作产物。

它不是整个实例 root。实例 root 更大，workspace 只是其中一块。

## 🧩 Instance Root 和 Workspace

实例 root 通常是：

```text
~/.nomi
```

workspace 通常是：

```text
~/.nomi/workspace
```

命名实例则是：

```text
~/.nomi/instances/<name>/workspace
```

## 📄 首次初始化会生成什么

workspace 初始化时会补这些文件：

```text
workspace/
├── AGENTS.md
├── SOUL.md
├── USER.md
└── memory/
    ├── MEMORY.md
    └── history.jsonl
```

`TOOLS.md` 不再生成到 workspace。工具说明由 core 内置模板注入 system prompt。

## 🧠 这些文件分别是什么

| 文件 | 用途 |
|---|---|
| `AGENTS.md` | 当前实例的项目/协作说明 |
| `SOUL.md` | 当前 Nomi 的自我设定 |
| `USER.md` | 用户画像和长期偏好 |
| `memory/MEMORY.md` | 长期记忆正文 |
| `memory/history.jsonl` | 记忆相关历史记录 |

## 🪪 名字同步

用户说“你现在就叫 xxx”时，模型会调用 `instance_set_name`。

这个动作会：

- 更新配置里的 `instance.key`。
- 同步更新 workspace 里的 `SOUL.md` 自称。

## 🧱 工作区纪律

Workspace 是长期目录，不是一次性临时目录。

模型应该：

- 先读后写。
- 不把临时调试文件堆在根目录。
- 把最终产物放在语义明确的位置。
- 不把工具说明复制进 workspace。
- 不把外部工具残留当作 Nomi 的长期文件。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/utils/workspace.py](../nomi/utils/workspace.py#L13-L64) | 同步 workspace 模板 |
| [nomi/utils/workspace.py](../nomi/utils/workspace.py#L67-L110) | instance 名字同步到 `SOUL.md` |
| [nomi/config/paths.py](../nomi/config/paths.py#L52-L61) | workspace 路径 |
| [nomi/templates/workspace/AGENTS.md](../nomi/templates/workspace/AGENTS.md#L1-L1) | 默认 AGENTS 模板 |
| [nomi/templates/workspace/SOUL.md](../nomi/templates/workspace/SOUL.md#L1-L9) | 默认 SOUL 模板 |
| [nomi/templates/workspace/USER.md](../nomi/templates/workspace/USER.md#L1-L30) | 默认 USER 模板 |
| [nomi/templates/TOOLS.md](../nomi/templates/TOOLS.md#L1-L157) | 内置工具说明模板 |
