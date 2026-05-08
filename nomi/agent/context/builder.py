"""负责组装 Agent 提示词与消息上下文。"""

from pathlib import Path
from typing import Any

from nomi.agent.context.runtime_blocks import (
    RUNTIME_CONTEXT_END,
    RUNTIME_CONTEXT_TAG,
    build_attachment_text,
    build_runtime_context,
    build_user_content,
    merge_message_content,
)
from nomi.agent.execution.messages import build_assistant_message
from nomi.agent.memory.store import MemoryStore
from nomi.agent.context.system_prompt import SystemPromptBuilder
from nomi.agent.skills.registry import SkillRegistry


class ContextBuilder:
    """负责把工作区状态整理成一次可直接发给模型的上下文。"""

    BOOTSTRAP_FILES = SystemPromptBuilder.BOOTSTRAP_FILES
    _RUNTIME_CONTEXT_TAG = RUNTIME_CONTEXT_TAG
    _RUNTIME_CONTEXT_END = RUNTIME_CONTEXT_END

    def __init__(
        self,
        workspace: Path,
        memory_store: MemoryStore,
        skill_registry: SkillRegistry,
        timezone: str | None = None,
    ):
        """绑定上下文构造所需的工作区依赖。

        这里不缓存最终提示词，只缓存读取入口，
        这样每一轮都能基于最新的记忆和启动文件重新组装上下文。
        """
        self.workspace = workspace
        self.timezone = timezone
        self.memory_store = memory_store
        self.skill_registry = skill_registry
        self._system_prompt_builder = SystemPromptBuilder(
            workspace,
            memory_store=memory_store,
            skill_registry=skill_registry,
        )

    def build_system_prompt(
        self,
        channel: str | None = None,
    ) -> str:
        """组装系统提示词主干。

        核心职责：
        - 写入身份与运行环境信息
        - 注入工作区启动文件
        - 拼接长期记忆
        - 在末尾补上近期未被 Dream 吸收的历史

        返回：
            可直接作为 `system` 消息发送的完整提示词文本。
        """
        return self._system_prompt_builder.build(channel=channel)

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        media: list[str] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        current_role: str = "user",
        session_summary: str | None = None,
        interrupted_context: str | None = None,
    ) -> list[dict[str, Any]]:
        """构造一次模型调用的完整消息数组。

        核心职责：
        - 补齐运行时元信息，避免模板层直接依赖外部状态
        - 把文本和媒体统一成 Provider 可接受的内容块
        - 在必要时与上一条同角色消息合并，规避部分 Provider 的协议限制

        返回：
            按当前 Provider 约定整理好的消息列表。
        """
        runtime_ctx = build_runtime_context(
            channel=channel,
            chat_id=chat_id,
            timezone=self.timezone,
            session_summary=session_summary,
            attachments=build_attachment_text(attachments),
            interrupted_context=interrupted_context,
        )
        user_content = build_user_content(
            text=current_message,
            media=media,
        )

        # 这里把运行时上下文和用户正文合并成一条消息，
        # 避免部分 Provider 拒绝连续出现相同 role 的消息。
        if isinstance(user_content, str):
            merged = f"{runtime_ctx}\n\n{user_content}"
        else:
            merged = [{"type": "text", "text": runtime_ctx}] + user_content
        messages = [
            {"role": "system", "content": self.build_system_prompt(channel=channel)},
            *history,
        ]
        if messages[-1].get("role") == current_role:
            last = dict(messages[-1])
            last["content"] = merge_message_content(last.get("content"), merged)
            messages[-1] = last
            return messages
        messages.append({"role": current_role, "content": merged})
        return messages

    def add_tool_result(
        self, messages: list[dict[str, Any]],
        tool_call_id: str, tool_name: str, result: Any,
    ) -> list[dict[str, Any]]:
        """把工具执行结果追加回消息链路。

        这里直接在原列表上追加，保持调用方持有的会话视图和实际发送顺序一致。
        """
        messages.append({"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result})
        return messages

    def add_assistant_message(
        self, messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
        reasoning_items: list[dict[str, Any]] | None = None,
        thinking_blocks: list[dict] | None = None,
    ) -> list[dict[str, Any]]:
        """把助手回复写回消息链路。

        之所以统一走 `build_assistant_message`，是为了让正文、工具调用和思考块的落盘结构保持一致，
        后续 Runner、Session 和测试都只需要面对一种助手消息格式。
        """
        messages.append(build_assistant_message(
            content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            reasoning_items=reasoning_items,
            thinking_blocks=thinking_blocks,
        ))
        return messages
