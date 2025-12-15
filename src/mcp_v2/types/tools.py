"""MCP Tools Types - Types for tool listing and invocation."""

from typing import Annotated, Any, Literal

from pydantic import Field

from mcp_v2.types.base import MCPModel, Meta, RequestParams, Result
from mcp_v2.types.common import Icon
from mcp_v2.types.content import ContentBlock
from mcp_v2.types.json_rpc import RequestBase


class ToolExecution(MCPModel):
    """Execution-related properties for a tool."""

    task_support: Annotated[
        Literal["forbidden", "optional", "required"] | None,
        Field(alias="taskSupport"),
    ] = None


class JsonSchema(MCPModel):
    """A JSON Schema object."""

    schema_: Annotated[str | None, Field(alias="$schema")] = None
    type: Literal["object"] = "object"
    properties: dict[str, Any] | None = None
    required: list[str] | None = None


class ToolAnnotations(MCPModel):
    """Additional properties describing a Tool to clients."""

    destructive_hint: Annotated[bool | None, Field(alias="destructiveHint")] = None
    idempotent_hint: Annotated[bool | None, Field(alias="idempotentHint")] = None
    open_world_hint: Annotated[bool | None, Field(alias="openWorldHint")] = None
    read_only_hint: Annotated[bool | None, Field(alias="readOnlyHint")] = None
    title: str | None = None


class Tool(MCPModel):
    """Definition of a tool the server provides."""

    # Required fields
    input_schema: Annotated[JsonSchema, Field(alias="inputSchema")]
    name: str

    # Optional fields (spec order)
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
    annotations: ToolAnnotations | None = None
    description: str | None = None
    execution: ToolExecution | None = None
    icons: list[Icon] | None = None
    output_schema: Annotated[JsonSchema | None, Field(alias="outputSchema")] = None
    title: str | None = None


class ListToolsRequestParams(RequestParams):
    """Parameters for tools/list request."""

    cursor: str | None = None


# PyCharm is dumb and doesn't understand `| None` and wants `Optional` instead, so ignoring.
# noinspection PyTypeChecker
class ListToolsRequest(RequestBase[Literal["tools/list"], ListToolsRequestParams | None]):
    """Request to list available tools."""

    method: Literal["tools/list"] = "tools/list"
    params: ListToolsRequestParams | None = None


class ListToolsResult(Result[Meta]):
    """Server's response to a tools/list request."""

    tools: list[Tool]
    next_cursor: Annotated[str | None, Field(alias="nextCursor")] = None


class CallToolRequestParams(RequestParams):
    """Parameters for tools/call request."""

    name: str
    arguments: dict[str, Any] | None = None


class CallToolRequest(RequestBase[Literal["tools/call"], CallToolRequestParams]):
    """Request to call a tool."""

    method: Literal["tools/call"] = "tools/call"


class CallToolResult(Result[Meta]):
    """Server's response to a tools/call request."""

    content: list[ContentBlock]
    structured_content: Annotated[dict[str, Any] | None, Field(alias="structuredContent")] = None
    is_error: Annotated[bool, Field(alias="isError")] = False
