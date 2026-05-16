"""Shared validation functions for server requests.

This module provides validation logic for sampling and elicitation requests
that is shared across normal and task-augmented code paths.
"""

from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, ClientCapabilities, SamplingMessage, SamplingMessageContentBlock, Tool, ToolChoice


def check_sampling_tools_capability(client_caps: ClientCapabilities | None) -> bool:
    """Check if the client supports sampling tools capability.

    Args:
        client_caps: The client's declared capabilities

    Returns:
        True if client supports sampling.tools, False otherwise
    """
    if client_caps is None:
        return False
    if client_caps.sampling is None:
        return False
    if client_caps.sampling.tools is None:
        return False
    return True


def validate_sampling_tools(
    client_caps: ClientCapabilities | None,
    tools: list[Tool] | None,
    tool_choice: ToolChoice | None,
) -> None:
    """Validate that the client supports sampling tools if tools are being used.

    Args:
        client_caps: The client's declared capabilities
        tools: The tools list, if provided
        tool_choice: The tool choice setting, if provided

    Raises:
        MCPError: If tools/tool_choice are provided but client doesn't support them
    """
    if tools is not None or tool_choice is not None:
        if not check_sampling_tools_capability(client_caps):
            raise MCPError(code=INVALID_PARAMS, message="Client does not support sampling tools capability")


def validate_tool_use_result_messages(messages: list[SamplingMessage]) -> None:
    """Validate tool_use/tool_result message structure per SEP-1577.

    This validation ensures:
    1. Messages with tool_result content contain ONLY tool_result content
    2. tool_result messages are preceded by a message with tool_use
    3. tool_result IDs match the tool_use IDs from the previous message
    4. Every tool_use message in the history is followed by matching tool_result content

    See: https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1577

    Args:
        messages: The list of sampling messages to validate

    Raises:
        ValueError: If the message structure is invalid
    """
    if not messages:
        return

    previous_content: list[SamplingMessageContentBlock] | None = None
    for content in (message.content_as_list for message in messages):
        has_tool_results = any(c.type == "tool_result" for c in content)
        previous_tool_use_ids: set[str] = set()
        if previous_content is not None:
            previous_tool_use_ids = {c.id for c in previous_content if c.type == "tool_use"}

        if has_tool_results:
            # Per spec: "SamplingMessage with tool result content blocks
            # MUST NOT contain other content types."
            if any(c.type != "tool_result" for c in content):
                raise ValueError("A message must contain only tool_result content if any is present")
            if previous_content is None:
                raise ValueError("tool_result requires a previous message containing tool_use")
            if not previous_tool_use_ids:
                raise ValueError("tool_result blocks do not match any tool_use in the previous message")

        if previous_tool_use_ids:
            tool_result_ids = {c.tool_use_id for c in content if c.type == "tool_result"}
            if previous_tool_use_ids != tool_result_ids:
                raise ValueError("ids of tool_result blocks and tool_use blocks from previous message do not match")

        previous_content = content
