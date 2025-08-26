"""
Tests for completion handler with context functionality.
"""

from typing import Any

import pytest

from mcp.server.lowlevel import Server
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import (
    Completion,
    CompletionArgument,
    CompletionContext,
    PromptReference,
    ResourceTemplateReference,
)


@pytest.mark.anyio
async def test_completion_handler_receives_context():
    """Test that the completion handler receives context correctly."""
    server = Server("test-server")

    # Track what the handler receives
    received_args: dict[str, Any] = {}

    @server.completion()
    async def handle_completion(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        received_args["ref"] = ref
        received_args["argument"] = argument
        received_args["context"] = context

        # Return test completion
        return Completion(values=["test-completion"], total=1, hasMore=False)

    async with create_connected_server_and_client_session(server) as client:
        # Test with context
        result = await client.complete(
            ref=ResourceTemplateReference(type="ref/resource", uri="test://resource/{param}"),
            argument={"name": "param", "value": "test"},
            context_arguments={"previous": "value"},
        )

        # Verify handler received the context
        assert received_args["context"] is not None
        assert received_args["context"].arguments == {"previous": "value"}
        assert result.completion.values == ["test-completion"]


@pytest.mark.anyio
async def test_completion_backward_compatibility():
    """Test that completion works without context (backward compatibility)."""
    server = Server("test-server")

    context_was_none = False

    @server.completion()
    async def handle_completion(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        nonlocal context_was_none
        context_was_none = context is None

        return Completion(values=["no-context-completion"], total=1, hasMore=False)

    async with create_connected_server_and_client_session(server) as client:
        # Test without context
        result = await client.complete(
            ref=PromptReference(type="ref/prompt", name="test-prompt"), argument={"name": "arg", "value": "val"}
        )

        # Verify context was None
        assert context_was_none
        assert result.completion.values == ["no-context-completion"]


@pytest.mark.anyio
async def test_dependent_completion_scenario():
    """Test a real-world scenario with dependent completions."""
    server = Server("test-server")

    @server.completion()
    async def handle_completion(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        # Simulate database/table completion scenario
        if isinstance(ref, ResourceTemplateReference):
            if ref.uri == "db://{database}/{table}":
                if argument.name == "database":
                    # Complete database names
                    return Completion(values=["users_db", "products_db", "analytics_db"], total=3, hasMore=False)
                elif argument.name == "table":
                    # Complete table names based on selected database
                    if context and context.arguments:
                        db = context.arguments.get("database")
                        if db == "users_db":
                            return Completion(values=["users", "sessions", "permissions"], total=3, hasMore=False)
                        elif db == "products_db":
                            return Completion(values=["products", "categories", "inventory"], total=3, hasMore=False)

        return Completion(values=[], total=0, hasMore=False)

    async with create_connected_server_and_client_session(server) as client:
        # First, complete database
        db_result = await client.complete(
            ref=ResourceTemplateReference(type="ref/resource", uri="db://{database}/{table}"),
            argument={"name": "database", "value": ""},
        )
        assert "users_db" in db_result.completion.values
        assert "products_db" in db_result.completion.values

        # Then complete table with database context
        table_result = await client.complete(
            ref=ResourceTemplateReference(type="ref/resource", uri="db://{database}/{table}"),
            argument={"name": "table", "value": ""},
            context_arguments={"database": "users_db"},
        )
        assert table_result.completion.values == ["users", "sessions", "permissions"]

        # Different database gives different tables
        table_result2 = await client.complete(
            ref=ResourceTemplateReference(type="ref/resource", uri="db://{database}/{table}"),
            argument={"name": "table", "value": ""},
            context_arguments={"database": "products_db"},
        )
        assert table_result2.completion.values == ["products", "categories", "inventory"]


@pytest.mark.anyio
async def test_completion_error_on_missing_context():
    """Test that server can raise error when required context is missing."""
    server = Server("test-server")

    @server.completion()
    async def handle_completion(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        if isinstance(ref, ResourceTemplateReference):
            if ref.uri == "db://{database}/{table}":
                if argument.name == "table":
                    # Check if database context is provided
                    if not context or not context.arguments or "database" not in context.arguments:
                        # Raise an error instead of returning error as completion
                        raise ValueError("Please select a database first to see available tables")
                    # Normal completion if context is provided
                    db = context.arguments.get("database")
                    if db == "test_db":
                        return Completion(values=["users", "orders", "products"], total=3, hasMore=False)

        return Completion(values=[], total=0, hasMore=False)

    async with create_connected_server_and_client_session(server) as client:
        # Try to complete table without database context - should raise error
        with pytest.raises(Exception) as exc_info:
            await client.complete(
                ref=ResourceTemplateReference(type="ref/resource", uri="db://{database}/{table}"),
                argument={"name": "table", "value": ""},
            )

        # Verify error message
        assert "Please select a database first" in str(exc_info.value)

        # Now complete with proper context - should work normally
        result_with_context = await client.complete(
            ref=ResourceTemplateReference(type="ref/resource", uri="db://{database}/{table}"),
            argument={"name": "table", "value": ""},
            context_arguments={"database": "test_db"},
        )

        # Should get normal completions
        assert result_with_context.completion.values == ["users", "orders", "products"]
