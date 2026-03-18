"""Integration tests for MCPServer server functionality.

These tests validate the proper functioning of MCPServer features using focused,
single-feature example servers over an in-memory transport.
"""
# TODO(Marcelo): The `examples` package is not being imported as package. We need to solve this.
# pyright: reportUnknownMemberType=false
# pyright: reportMissingImports=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import json

import pytest
from inline_snapshot import snapshot

from examples.snippets.servers import (
    basic_prompt,
    basic_resource,
    basic_tool,
    completion,
    elicitation,
    mcpserver_quickstart,
    notifications,
    sampling,
    structured_output,
    tool_progress,
)
from mcp.client import Client
from mcp.client.session import ClientSession
from mcp.shared._context import RequestContext
from mcp.shared.session import RequestResponder
from mcp.types import (
    ClientResult,
    CreateMessageRequestParams,
    CreateMessageResult,
    ElicitRequestParams,
    ElicitResult,
    GetPromptResult,
    LoggingMessageNotification,
    LoggingMessageNotificationParams,
    NotificationParams,
    ProgressNotification,
    ProgressNotificationParams,
    PromptReference,
    ReadResourceResult,
    ResourceListChangedNotification,
    ResourceTemplateReference,
    ServerNotification,
    ServerRequest,
    TextContent,
    TextResourceContents,
    ToolListChangedNotification,
)

pytestmark = pytest.mark.anyio


class NotificationCollector:
    """Collects notifications from the server for testing."""

    def __init__(self):
        self.progress_notifications: list[ProgressNotificationParams] = []
        self.log_messages: list[LoggingMessageNotificationParams] = []
        self.resource_notifications: list[NotificationParams | None] = []
        self.tool_notifications: list[NotificationParams | None] = []

    async def handle_generic_notification(
        self, message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception
    ) -> None:
        """Handle any server notification and route to appropriate handler."""
        if isinstance(message, ServerNotification):  # pragma: no branch
            if isinstance(message, ProgressNotification):
                self.progress_notifications.append(message.params)
            elif isinstance(message, LoggingMessageNotification):
                self.log_messages.append(message.params)
            elif isinstance(message, ResourceListChangedNotification):
                self.resource_notifications.append(message.params)
            elif isinstance(message, ToolListChangedNotification):  # pragma: no cover
                self.tool_notifications.append(message.params)


async def sampling_callback(
    context: RequestContext[ClientSession], params: CreateMessageRequestParams
) -> CreateMessageResult:
    """Sampling callback for tests."""
    return CreateMessageResult(
        role="assistant",
        content=TextContent(
            type="text",
            text="This is a simulated LLM response for testing",
        ),
        model="test-model",
    )


async def elicitation_callback(context: RequestContext[ClientSession], params: ElicitRequestParams):
    """Elicitation callback for tests."""
    # For restaurant booking test
    if "No tables available" in params.message:
        return ElicitResult(
            action="accept",
            content={"checkAlternative": True, "alternativeDate": "2024-12-26"},
        )
    else:  # pragma: no cover
        return ElicitResult(action="decline")


async def test_basic_tools() -> None:
    """Test basic tool functionality."""
    async with Client(basic_tool.mcp) as client:
        assert client.server_capabilities is not None
        assert client.server_capabilities.tools is not None

        # Test sum tool
        tool_result = await client.call_tool("sum", {"a": 5, "b": 3})
        assert len(tool_result.content) == 1
        assert isinstance(tool_result.content[0], TextContent)
        assert tool_result.content[0].text == "8"

        # Test weather tool
        weather_result = await client.call_tool("get_weather", {"city": "London"})
        assert len(weather_result.content) == 1
        assert isinstance(weather_result.content[0], TextContent)
        assert "Weather in London: 22degreesC" in weather_result.content[0].text


async def test_basic_resources() -> None:
    """Test basic resource functionality."""
    async with Client(basic_resource.mcp) as client:
        assert client.server_capabilities is not None
        assert client.server_capabilities.resources is not None

        # Test document resource
        doc_content = await client.read_resource("file://documents/readme")
        assert isinstance(doc_content, ReadResourceResult)
        assert len(doc_content.contents) == 1
        assert isinstance(doc_content.contents[0], TextResourceContents)
        assert "Content of readme" in doc_content.contents[0].text

        # Test settings resource
        settings_content = await client.read_resource("config://settings")
        assert isinstance(settings_content, ReadResourceResult)
        assert len(settings_content.contents) == 1
        assert isinstance(settings_content.contents[0], TextResourceContents)
        settings_json = json.loads(settings_content.contents[0].text)
        assert settings_json["theme"] == "dark"
        assert settings_json["language"] == "en"


async def test_basic_prompts() -> None:
    """Test basic prompt functionality."""
    async with Client(basic_prompt.mcp) as client:
        assert client.server_capabilities is not None
        assert client.server_capabilities.prompts is not None

        # Test review_code prompt
        prompts = await client.list_prompts()
        review_prompt = next((p for p in prompts.prompts if p.name == "review_code"), None)
        assert review_prompt is not None

        prompt_result = await client.get_prompt("review_code", {"code": "def hello():\n    print('Hello')"})
        assert isinstance(prompt_result, GetPromptResult)
        assert len(prompt_result.messages) == 1
        assert isinstance(prompt_result.messages[0].content, TextContent)
        assert "Please review this code:" in prompt_result.messages[0].content.text
        assert "def hello():" in prompt_result.messages[0].content.text

        # Test debug_error prompt
        debug_result = await client.get_prompt(
            "debug_error", {"error": "TypeError: 'NoneType' object is not subscriptable"}
        )
        assert isinstance(debug_result, GetPromptResult)
        assert len(debug_result.messages) == 3
        assert debug_result.messages[0].role == "user"
        assert isinstance(debug_result.messages[0].content, TextContent)
        assert "I'm seeing this error:" in debug_result.messages[0].content.text
        assert debug_result.messages[1].role == "user"
        assert isinstance(debug_result.messages[1].content, TextContent)
        assert "TypeError" in debug_result.messages[1].content.text
        assert debug_result.messages[2].role == "assistant"
        assert isinstance(debug_result.messages[2].content, TextContent)
        assert "I'll help debug that" in debug_result.messages[2].content.text


async def test_tool_progress() -> None:
    """Test tool progress reporting."""
    collector = NotificationCollector()

    async def message_handler(message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception):
        await collector.handle_generic_notification(message)
        if isinstance(message, Exception):  # pragma: no cover
            raise message

    async with Client(tool_progress.mcp, message_handler=message_handler) as client:
        # Test progress callback
        progress_updates = []

        async def progress_callback(progress: float, total: float | None, message: str | None) -> None:
            progress_updates.append((progress, total, message))

        # Call tool with progress
        steps = 3
        tool_result = await client.call_tool(
            "long_running_task",
            {"task_name": "Test Task", "steps": steps},
            progress_callback=progress_callback,
        )
        assert tool_result.content == snapshot([TextContent(text="Task 'Test Task' completed")])

        # Verify progress updates
        assert len(progress_updates) == steps
        for i, (progress, total, message) in enumerate(progress_updates):
            expected_progress = (i + 1) / steps
            assert abs(progress - expected_progress) < 0.01
            assert total == 1.0
            assert f"Step {i + 1}/{steps}" in message

        # Verify log messages
        assert len(collector.log_messages) > 0


async def test_sampling() -> None:
    """Test sampling (LLM interaction) functionality."""
    async with Client(sampling.mcp, sampling_callback=sampling_callback) as client:
        assert client.server_capabilities is not None
        assert client.server_capabilities.tools is not None

        # Test sampling tool
        sampling_result = await client.call_tool("generate_poem", {"topic": "nature"})
        assert len(sampling_result.content) == 1
        assert isinstance(sampling_result.content[0], TextContent)
        assert "This is a simulated LLM response" in sampling_result.content[0].text


async def test_elicitation() -> None:
    """Test elicitation (user interaction) functionality."""
    async with Client(elicitation.mcp, elicitation_callback=elicitation_callback) as client:
        # Test booking with unavailable date (triggers elicitation)
        booking_result = await client.call_tool(
            "book_table",
            {
                "date": "2024-12-25",  # Unavailable date
                "time": "19:00",
                "party_size": 4,
            },
        )
        assert len(booking_result.content) == 1
        assert isinstance(booking_result.content[0], TextContent)
        assert "[SUCCESS] Booked for 2024-12-26" in booking_result.content[0].text

        # Test booking with available date (no elicitation)
        booking_result = await client.call_tool(
            "book_table",
            {
                "date": "2024-12-20",  # Available date
                "time": "20:00",
                "party_size": 2,
            },
        )
        assert len(booking_result.content) == 1
        assert isinstance(booking_result.content[0], TextContent)
        assert "[SUCCESS] Booked for 2024-12-20 at 20:00" in booking_result.content[0].text


async def test_notifications() -> None:
    """Test notifications and logging functionality."""
    collector = NotificationCollector()

    async def message_handler(message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception):
        await collector.handle_generic_notification(message)
        if isinstance(message, Exception):  # pragma: no cover
            raise message

    async with Client(notifications.mcp, message_handler=message_handler) as client:
        # Call tool that generates notifications
        tool_result = await client.call_tool("process_data", {"data": "test_data"})
        assert len(tool_result.content) == 1
        assert isinstance(tool_result.content[0], TextContent)
        assert "Processed: test_data" in tool_result.content[0].text

        # Verify log messages at different levels
        assert len(collector.log_messages) >= 4
        log_levels = {msg.level for msg in collector.log_messages}
        assert "debug" in log_levels
        assert "info" in log_levels
        assert "warning" in log_levels
        assert "error" in log_levels

        # Verify resource list changed notification
        assert len(collector.resource_notifications) > 0


async def test_completion() -> None:
    """Test completion (autocomplete) functionality."""
    async with Client(completion.mcp) as client:
        assert client.server_capabilities is not None
        assert client.server_capabilities.resources is not None
        assert client.server_capabilities.prompts is not None

        # Test resource completion
        completion_result = await client.complete(
            ref=ResourceTemplateReference(type="ref/resource", uri="github://repos/{owner}/{repo}"),
            argument={"name": "repo", "value": ""},
            context_arguments={"owner": "modelcontextprotocol"},
        )

        assert completion_result is not None
        assert hasattr(completion_result, "completion")
        assert completion_result.completion is not None
        assert len(completion_result.completion.values) == 3
        assert "python-sdk" in completion_result.completion.values
        assert "typescript-sdk" in completion_result.completion.values
        assert "specification" in completion_result.completion.values

        # Test prompt completion
        completion_result = await client.complete(
            ref=PromptReference(type="ref/prompt", name="review_code"),
            argument={"name": "language", "value": "py"},
        )

        assert completion_result is not None
        assert hasattr(completion_result, "completion")
        assert completion_result.completion is not None
        assert "python" in completion_result.completion.values
        assert all(lang.startswith("py") for lang in completion_result.completion.values)


async def test_mcpserver_quickstart() -> None:
    """Test MCPServer quickstart example."""
    async with Client(mcpserver_quickstart.mcp) as client:
        # Test add tool
        tool_result = await client.call_tool("add", {"a": 10, "b": 20})
        assert len(tool_result.content) == 1
        assert isinstance(tool_result.content[0], TextContent)
        assert tool_result.content[0].text == "30"

        # Test greeting resource directly
        resource_result = await client.read_resource("greeting://Alice")
        assert len(resource_result.contents) == 1
        assert isinstance(resource_result.contents[0], TextResourceContents)
        assert resource_result.contents[0].text == "Hello, Alice!"


async def test_structured_output() -> None:
    """Test structured output functionality."""
    async with Client(structured_output.mcp) as client:
        # Test get_weather tool
        weather_result = await client.call_tool("get_weather", {"city": "New York"})
        assert len(weather_result.content) == 1
        assert isinstance(weather_result.content[0], TextContent)

        # Check that the result contains expected weather data
        result_text = weather_result.content[0].text
        assert "22.5" in result_text  # temperature
        assert "sunny" in result_text  # condition
        assert "45" in result_text  # humidity
        assert "5.2" in result_text  # wind_speed
