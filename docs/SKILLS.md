# 📦 Skills

Skills 是给 Nomi 扩展专业工作流的说明包。它不是普通工具，也不是硬编码 prompt，而是一组安装到实例里的文件说明。

模型看到 skill 摘要后，会在需要时读取对应 `SKILL.md`，再按里面的流程继续读取模板、参考资料或脚本。

## 🌟 Skill 能做什么

Skill 适合封装：

- 某类 API 的固定使用流程。
- 某类文档、表格、PDF 的处理规范。
- 某个工具链的操作步骤。
- 带模板、示例、脚本的复杂任务。

## 📁 安装位置

当前实例的 skill root 是：

```text
<instance-root>/skills
```

默认实例就是：

```text
~/.nomi/skills
```

外部 roots 例如 `~/.codex/skills`、`~/.claude/skills` 只作为安装来源，不作为运行时扫描根。

## 🧩 最小结构

一个最小 skill：

```text
my-skill/
└── SKILL.md
```

更完整时可以有：

```text
my-skill/
├── SKILL.md
├── template.md
├── references/
├── examples/
└── scripts/
```

## 💬 用户怎么用

用户可以说：

```text
安装这个 skill。
列出现在有哪些 skill。
创建一个处理合同的 skill。
卸载 xxx skill。
```

也可以使用 slash command：

```text
/skill list
/skill install <source>
/skill uninstall <name>
```

## 🧠 模型怎么知道 skill

System prompt 里只注入 skill 摘要：

- skill key
- name
- description
- `SKILL.md` 路径

skill 正文不会默认整篇注入。模型需要时再读取对应文件。

## 🧱 边界

- Skill 不是工具调用本身。
- Skill 不会自动执行脚本；模型必须按说明决定是否调用工具。
- Skill 安装到当前实例，不是全局跨实例共享。
- 同名 skill 已存在时，需要先卸载再安装。

## 🔎 相关代码

| 代码 | 说明 |
|---|---|
| [nomi/agent/skills/manager.py](../nomi/agent/skills/manager.py#L44-L197) | skill 安装、卸载、创建 |
| [nomi/agent/skills/registry.py](../nomi/agent/skills/registry.py#L15-L147) | skill 扫描和 prompt 摘要 |
| [nomi/agent/skills/parser.py](../nomi/agent/skills/parser.py#L1-L60) | `SKILL.md` metadata 解析 |
| [nomi/agent/tools/skill_tools.py](../nomi/agent/tools/skill_tools.py#L1-L425) | skill 相关工具 |
| [nomi/command/handlers/skills.py](../nomi/command/handlers/skills.py#L1-L98) | `/skill` 命令 |
| [nomi/config/paths.py](../nomi/config/paths.py#L30-L52) | skill root 路径 |
