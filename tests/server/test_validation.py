"""Tests for server validation functions."""

import pytest

from mcp.server.validation import (
    check_sampling_tools_capability,
    validate_sampling_tools,
    validate_tool_use_result_messages,
)
from mcp.shared.exceptions import McpError
from mcp.types import (
    ClientCapabilities,
    SamplingCapability,
    SamplingMessage,
    SamplingToolsCapability,
    TextContent,
    Tool,
    ToolChoice,
    ToolResultContent,
    ToolUseContent,
)


class TestCheckSamplingToolsCapability:
    """Tests for check_sampling_tools_capability function."""

    def test_returns_false_when_caps_none(self) -> None:
        """Returns False when client_caps is None."""
        assert check_sampling_tools_capability(None) is False

    def test_returns_false_when_sampling_none(self) -> None:
        """Returns False when client_caps.sampling is None."""
        caps = ClientCapabilities()
        assert check_sampling_tools_capability(caps) is False

    def test_returns_false_when_tools_none(self) -> None:
        """Returns False when client_caps.sampling.tools is None."""
        caps = ClientCapabilities(sampling=SamplingCapability())
        assert check_sampling_tools_capability(caps) is False

    def test_returns_true_when_tools_present(self) -> None:
        """Returns True when sampling.tools is present."""
        caps = ClientCapabilities(sampling=SamplingCapability(tools=SamplingToolsCapability()))
        assert check_sampling_tools_capability(caps) is True


class TestValidateSamplingTools:
    """Tests for validate_sampling_tools function."""

    def test_no_error_when_tools_none(self) -> None:
        """No error when tools and tool_choice are None."""
        validate_sampling_tools(None, None, None)  # Should not raise

    def test_raises_when_tools_provided_but_no_capability(self) -> None:
        """Raises McpError when tools provided but client doesn't support."""
        tool = Tool(name="test", inputSchema={"type": "object"})
        with pytest.raises(McpError) as exc_info:
            validate_sampling_tools(None, [tool], None)
        assert "sampling tools capability" in str(exc_info.value)

    def test_raises_when_tool_choice_provided_but_no_capability(self) -> None:
        """Raises McpError when tool_choice provided but client doesn't support."""
        with pytest.raises(McpError) as exc_info:
            validate_sampling_tools(None, None, ToolChoice(mode="auto"))
        assert "sampling tools capability" in str(exc_info.value)

    def test_no_error_when_capability_present(self) -> None:
        """No error when client has sampling.tools capability."""
        caps = ClientCapabilities(sampling=SamplingCapability(tools=SamplingToolsCapability()))
        tool = Tool(name="test", inputSchema={"type": "object"})
        validate_sampling_tools(caps, [tool], ToolChoice(mode="auto"))  # Should not raise


class TestValidateToolUseResultMessages:
    """Tests for validate_tool_use_result_messages function."""

    def test_no_error_for_empty_messages(self) -> None:
        """No error when messages list is empty."""
        validate_tool_use_result_messages([])  # Should not raise

    def test_no_error_for_simple_text_messages(self) -> None:
        """No error for simple text messages."""
        messages = [
            SamplingMessage(role="user", content=TextContent(type="text", text="Hello")),
            SamplingMessage(role="assistant", content=TextContent(type="text", text="Hi")),
        ]
        validate_tool_use_result_messages(messages)  # Should not raise

    def test_raises_when_tool_result_mixed_with_other_content(self) -> None:
        """Raises when tool_result is mixed with other content types."""
        messages = [
            SamplingMessage(
                role="user",
                content=[
                    ToolResultContent(type="tool_result", toolUseId="123"),
                    TextContent(type="text", text="also this"),
                ],
            ),
        ]
        with pytest.raises(ValueError, match="only tool_result content"):
            validate_tool_use_result_messages(messages)

    def test_raises_when_tool_result_without_previous_tool_use(self) -> None:
        """Raises when tool_result appears without preceding tool_use."""
        messages = [
            SamplingMessage(
                role="user",
                content=ToolResultContent(type="tool_result", toolUseId="123"),
            ),
        ]
        with pytest.raises(ValueError, match="previous message containing tool_use"):
            validate_tool_use_result_messages(messages)

    def test_raises_when_tool_result_ids_dont_match_tool_use(self) -> None:
        """Raises when tool_result IDs don't match tool_use IDs."""
        messages = [
            SamplingMessage(
                role="assistant",
                content=ToolUseContent(type="tool_use", id="tool-1", name="test", input={}),
            ),
            SamplingMessage(
                role="user",
                content=ToolResultContent(type="tool_result", toolUseId="tool-2"),
            ),
        ]
        with pytest.raises(ValueError, match="do not match"):
            validate_tool_use_result_messages(messages)

    def test_no_error_when_tool_result_matches_tool_use(self) -> None:
        """No error when tool_result IDs match tool_use IDs."""
        messages = [
            SamplingMessage(
                role="assistant",
                content=ToolUseContent(type="tool_use", id="tool-1", name="test", input={}),
            ),
            SamplingMessage(
                role="user",
                content=ToolResultContent(type="tool_result", toolUseId="tool-1"),
            ),
        ]
        validate_tool_use_result_messages(messages)  # Should not raise
