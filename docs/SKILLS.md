# 📦 Skills

Skills 是当前实例下的“任务说明包”机制 📦

它不是 tool，也不是硬编码在 prompt 里的几段死文本。

更准确地说，它是：

- 扫描 `~/.nomi/skills` 🔎
- 把 skill metadata 注入 system prompt 🧠
- 在需要时允许模型读取 skill 文件正文 📄

---

## 目录位置

全局 skills 目录默认是：

```text
~/.nomi/skills
```

命名实例下则是：

```text
<instance-root>/skills
```

路径逻辑在 [nomi/config/paths.py](../nomi/config/paths.py#L30-L52)。

它是当前实例内唯一的 canonical root。`SkillRegistry` 只扫描这里，`SkillManager` 也只把这里当成正式安装目录。

系统还支持一组外部 skill roots，默认包括：

```text
~/.claude/skills
~/.codex/skills
```

外部 roots 只作为安装时的一次性导入来源，不作为直接扫描结果输出路径。

---

## 一个 skill 的最小结构

```text
~/.nomi/skills/my-skill/
└── SKILL.md
```

更完整时可以有：

```text
~/.nomi/skills/my-skill/
├── SKILL.md
├── template.md
├── references/
├── examples/
└── scripts/
```

---

## 元数据解析

`SKILL.md` 当前支持 frontmatter 里的基础字段：

- `name`
- `description`

扫描与解析相关代码：

- registry：[nomi/agent/skills/registry.py](../nomi/agent/skills/registry.py#L14-L144)
- parser：[nomi/agent/skills/parser.py](../nomi/agent/skills/parser.py)

---

## Prompt 注入方式

当前 skills 不会把正文自动全部塞进 system prompt。

它只会注入：

- key
- name
- description
- `SKILL.md` 路径

见 [nomi/agent/skills/registry.py](../nomi/agent/skills/registry.py#L54-L79)。

这意味着：

- skills 默认是“告诉模型可用什么”
- 模型是否继续读取 skill 正文，要看具体任务

---

## 管理命令

当前 slash 命令支持：

- `/skill list`
- `/skill install <source>`
- `/skill uninstall <name>`

入口在 [nomi/command/handlers/skills.py](../nomi/command/handlers/skills.py#L11-L98)。

### `list`

会扫描当前全局 skills 并生成展示文本。

### `install`

通过 `SkillManager` 安装 skill。

### `uninstall`

通过 `SkillManager` 卸载 skill。

当前只有在安装 skill 包时，才会按需做一次外部 roots 导入：

- 非 Windows：优先创建符号链接
- Windows：回退为复制
- 若目标 canonical 路径已存在，则跳过，不覆盖外部来源
- `list_skills` / `SkillRegistry.scan()` 不会持续自动补回外部 skill

当前模型侧默认工具还包括：

- `list_skills`
- `find_skills`
- `install_skill`
- `create_skill`
- `uninstall_skill`

其中：

- `find_skills` 会先看本地已安装 skill，再调用 `npx skills find` 搜索外部技能生态
- `install_skill` 现在除了本地目录、压缩包、Git 链接，也支持 `owner/repo@skill` 这类 skills 包来源
- `create_skill` 会直接在 `~/.nomi/skills` 下生成最小 `SKILL.md` 脚手架

---

## SkillManager 和 SkillRegistry 的边界

这两者当前已经分工很清楚：

### `SkillRegistry`

只读 owner，负责：

- 扫描 skills 目录
- 解析 metadata
- 生成 prompt summary
- 列出当前状态

见 [nomi/agent/skills/registry.py](../nomi/agent/skills/registry.py#L14-L144)。

### `SkillManager`

写操作 owner，负责：

- 安装
- 卸载
- 在安装外部 skill 包时，把外部 roots 里的结果一次性导入 canonical root

当前文档里不要再把这两者混成一个“大技能系统类”。

---

## Skill 使用日志

当前 skill registry 还支持记录 usage：

- 显式提到 skill 时
- 或模型路径触发时

记录接口在 [nomi/agent/skills/registry.py](../nomi/agent/skills/registry.py#L99-L133)。

日志文件路径由：

- [nomi/config/paths.py](../nomi/config/paths.py#L47-L49)

返回。

---

## 主链路里怎么接入

当前 `AgentLoop` 初始化时会创建：

- `SkillRegistry`

并把它传给 `ContextBuilder`：

- [nomi/agent/loop.py](../nomi/agent/loop.py#L145-L153)

所以 skills 现在已经是系统 prompt 的一部分，而不是 CLI 的附加功能。

---

## 当前边界

skills 当前是“全局任务知识与工作流说明”的系统，不是：

- marketplace
- 权限中心
- 复杂插件平台

如果文档把它写得太重，会误导后续实现方向。
