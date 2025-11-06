"""Tests for task execution capabilities."""

from typing import Any

from pydantic import AnyUrl

from examples.shared.in_memory_task_store import InMemoryTaskStore
from mcp import types
from mcp.server.lowlevel import NotificationOptions, Server


class TestCapabilitySerialization:
    """Test that task capabilities serialize/deserialize correctly."""

    def test_client_tasks_capability_full(self):
        """Test full client tasks capability serialization."""
        cap = types.ClientTasksCapability(
            requests=types.ClientTasksRequestsCapability(
                sampling=types.TaskSamplingCapability(createMessage=True),
                elicitation=types.TaskElicitationCapability(create=True),
                roots=types.TaskRootsCapability(list=True),
                tasks=types.TasksOperationsCapability(get=True, list=True, result=True, delete=True),
            )
        )
        # Serialize and deserialize
        data = cap.model_dump(by_alias=True, mode="json", exclude_none=True)
        deserialized = types.ClientTasksCapability.model_validate(data)
        assert deserialized.requests is not None
        assert deserialized.requests.sampling is not None
        assert deserialized.requests.sampling.createMessage is True
        assert deserialized.requests.elicitation is not None
        assert deserialized.requests.elicitation.create is True
        assert deserialized.requests.roots is not None
        assert deserialized.requests.roots.list is True
        assert deserialized.requests.tasks is not None
        assert deserialized.requests.tasks.get is True
        assert deserialized.requests.tasks.list is True
        assert deserialized.requests.tasks.result is True
        assert deserialized.requests.tasks.delete is True

    def test_server_tasks_capability_full(self):
        """Test full server tasks capability serialization."""
        cap = types.ServerTasksCapability(
            requests=types.ServerTasksRequestsCapability(
                tools=types.TaskToolsCapability(call=True, list=True),
                resources=types.TaskResourcesCapability(read=True, list=True),
                prompts=types.TaskPromptsCapability(get=True, list=True),
                tasks=types.TasksOperationsCapability(get=True, list=True, result=True, delete=True),
            )
        )
        # Serialize and deserialize
        data = cap.model_dump(by_alias=True, mode="json", exclude_none=True)
        deserialized = types.ServerTasksCapability.model_validate(data)
        assert deserialized.requests is not None
        assert deserialized.requests.tools is not None
        assert deserialized.requests.tools.call is True
        assert deserialized.requests.tools.list is True
        assert deserialized.requests.resources is not None
        assert deserialized.requests.resources.read is True
        assert deserialized.requests.resources.list is True
        assert deserialized.requests.prompts is not None
        assert deserialized.requests.prompts.get is True
        assert deserialized.requests.prompts.list is True
        assert deserialized.requests.tasks is not None
        assert deserialized.requests.tasks.get is True
        assert deserialized.requests.tasks.list is True
        assert deserialized.requests.tasks.result is True
        assert deserialized.requests.tasks.delete is True

    def test_client_capabilities_with_tasks(self):
        """Test ClientCapabilities with tasks field."""
        caps = types.ClientCapabilities(
            sampling=types.SamplingCapability(),
            tasks=types.ClientTasksCapability(
                requests=types.ClientTasksRequestsCapability(tasks=types.TasksOperationsCapability(get=True, list=True))
            ),
        )
        data = caps.model_dump(by_alias=True, mode="json", exclude_none=True)
        deserialized = types.ClientCapabilities.model_validate(data)
        assert deserialized.tasks is not None
        assert deserialized.tasks.requests is not None
        assert deserialized.tasks.requests.tasks is not None
        assert deserialized.tasks.requests.tasks.get is True
        assert deserialized.tasks.requests.tasks.list is True

    def test_server_capabilities_with_tasks(self):
        """Test ServerCapabilities with tasks field."""
        caps = types.ServerCapabilities(
            logging=types.LoggingCapability(),
            tasks=types.ServerTasksCapability(
                requests=types.ServerTasksRequestsCapability(
                    tools=types.TaskToolsCapability(call=True),
                    tasks=types.TasksOperationsCapability(get=True, delete=True),
                )
            ),
        )
        data = caps.model_dump(by_alias=True, mode="json", exclude_none=True)
        deserialized = types.ServerCapabilities.model_validate(data)
        assert deserialized.tasks is not None
        assert deserialized.tasks.requests is not None
        assert deserialized.tasks.requests.tools is not None
        assert deserialized.tasks.requests.tools.call is True
        assert deserialized.tasks.requests.tasks is not None
        assert deserialized.tasks.requests.tasks.get is True
        assert deserialized.tasks.requests.tasks.delete is True


class TestServerCapabilityAdvertisement:
    """Test that server advertises task capabilities correctly."""

    def test_no_tasks_capability_without_task_store(self):
        """Server should not advertise tasks capability without task store."""
        server = Server("test")
        caps = server.get_capabilities(NotificationOptions(), {})
        assert caps.tasks is None

    def test_tasks_capability_with_task_store(self):
        """Server should advertise tasks capability with task store."""
        task_store = InMemoryTaskStore()
        server = Server("test", task_store=task_store)
        caps = server.get_capabilities(NotificationOptions(), {})
        assert caps.tasks is not None
        assert caps.tasks.requests is not None
        assert caps.tasks.requests.tasks is not None
        # All task operations should be available
        assert caps.tasks.requests.tasks.get is True
        assert caps.tasks.requests.tasks.list is True
        assert caps.tasks.requests.tasks.result is True
        assert caps.tasks.requests.tasks.delete is True

    def test_tasks_capability_includes_tools_when_available(self):
        """Server should include tools in tasks capability when handler exists."""
        task_store = InMemoryTaskStore()
        server = Server("test", task_store=task_store)

        # Register tool handler
        @server.call_tool()
        async def my_tool(arguments: dict[str, Any]) -> list[types.TextContent]:
            return [types.TextContent(type="text", text="test")]

        caps = server.get_capabilities(NotificationOptions(), {})
        assert caps.tasks is not None
        assert caps.tasks.requests is not None
        assert caps.tasks.requests.tools is not None
        assert caps.tasks.requests.tools.call is True

    def test_tasks_capability_includes_resources_when_available(self):
        """Server should include resources in tasks capability when handler exists."""
        task_store = InMemoryTaskStore()
        server = Server("test", task_store=task_store)

        # Register resource handler
        @server.read_resource()
        async def read_resource(uri: AnyUrl) -> str:
            return "test"

        caps = server.get_capabilities(NotificationOptions(), {})
        assert caps.tasks is not None
        assert caps.tasks.requests is not None
        assert caps.tasks.requests.resources is not None
        assert caps.tasks.requests.resources.read is True

    def test_tasks_capability_includes_prompts_when_available(self):
        """Server should include prompts in tasks capability when handler exists."""
        task_store = InMemoryTaskStore()
        server = Server("test", task_store=task_store)

        # Register prompt handler
        @server.get_prompt()
        async def get_prompt(name: str, arguments: dict[str, str] | None = None) -> types.GetPromptResult:
            return types.GetPromptResult(
                messages=[types.PromptMessage(role="user", content=types.TextContent(type="text", text="test"))]
            )

        caps = server.get_capabilities(NotificationOptions(), {})
        assert caps.tasks is not None
        assert caps.tasks.requests is not None
        assert caps.tasks.requests.prompts is not None
        assert caps.tasks.requests.prompts.get is True


# Note: Additional integration tests for client capability announcement and validation
# are covered by the existing test suite which uses create_connected_server_and_client_session()
