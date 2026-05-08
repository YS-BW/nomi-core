from __future__ import annotations

import json
from typing import Any

from nomi.agent.tools import StringSchema, tool_parameters, tool_parameters_schema
from nomi.agent.tools.base import Tool
from nomi.agent.tools.registry import ToolRegistry
from nomi.providers.backends.anthropic import AnthropicProvider
from nomi.providers.openai_responses.converters import convert_tools


@tool_parameters(
    tool_parameters_schema(
        config={
            "type": "object",
            "properties": {
                "label": StringSchema("label"),
                "nested": {
                    "type": "array",
                    "items": StringSchema("nested item"),
                },
            },
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "tag": StringSchema("tag"),
                },
            },
        },
        required=["config"],
    )
)
class _NestedTool(Tool):
    @property
    def name(self) -> str:
        return "nested_tool"

    @property
    def description(self) -> str:
        return "nested schema tool"

    async def execute(self, **kwargs: Any) -> str:
        return "ok"


def test_anthropic_tool_conversion_normalizes_nested_schema() -> None:
    registry = ToolRegistry()
    registry.register(_NestedTool())

    tools = registry.get_definitions()
    converted = AnthropicProvider._convert_tools(tools)

    assert converted is not None
    payload = json.dumps(converted, ensure_ascii=False)

    assert "StringSchema" not in payload
    assert converted[0]["input_schema"]["properties"]["config"]["properties"]["label"]["type"] == "string"
    assert (
        converted[0]["input_schema"]["properties"]["config"]["additionalProperties"]["properties"]["tag"]["type"]
        == "string"
    )


def test_anthropic_tool_conversion_normalizes_raw_schema_objects() -> None:
    tools = [
        {
            "function": {
                "name": "raw_schema",
                "description": "raw schema",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": StringSchema("query"),
                        "nested": {
                            "type": "array",
                            "items": StringSchema("nested item"),
                        },
                    },
                },
            }
        }
    ]

    converted = AnthropicProvider._convert_tools(tools)

    assert converted is not None
    payload = json.dumps(converted, ensure_ascii=False)

    assert "StringSchema" not in payload
    assert converted[0]["input_schema"]["properties"]["query"]["type"] == "string"
    assert converted[0]["input_schema"]["properties"]["nested"]["items"]["type"] == "string"


def test_openai_responses_convert_tools_normalizes_raw_schema_objects() -> None:
    tools = [
        {
            "function": {
                "name": "raw_schema",
                "description": "raw schema",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": StringSchema("query"),
                        "nested": {
                            "type": "array",
                            "items": StringSchema("nested item"),
                        },
                    },
                },
            }
        }
    ]

    converted = convert_tools(tools)

    assert json.dumps(converted, ensure_ascii=False)
    assert converted[0]["parameters"]["properties"]["query"]["type"] == "string"
    assert converted[0]["parameters"]["properties"]["nested"]["items"]["type"] == "string"
