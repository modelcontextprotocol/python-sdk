"""Tests for completion handler with context functionality."""

import pytest

from mcp import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    CompleteRequestParams,
    CompleteResult,
    Completion,
    PromptReference,
    ResourceTemplateReference,
)


@pytest.mark.anyio
async def test_completion_handler_receives_context():
    """Test that the completion handler receives context correctly."""
    # Track what the handler receives
    received_params: CompleteRequestParams | None = None

    async def handle_completion(ctx: ServerRequestContext, params: CompleteRequestParams) -> CompleteResult:
        nonlocal received_params
        received_params = params
        return CompleteResult(completion=Completion(values=["test-completion"], total=1, has_more=False))

    server = Server("test-server", on_completion=handle_completion)

    async with Client(server) as client:
        # Test with context
        result = await client.complete(
            ref=ResourceTemplateReference(type="ref/resource", uri="test://resource/{param}"),
            argument={"name": "param", "value": "test"},
            context_arguments={"previous": "value"},
        )

        # Verify handler received the context
        assert received_params is not None
        assert received_params.context is not None
        assert received_params.context.arguments == {"previous": "value"}
        assert result.completion.values == ["test-completion"]


@pytest.mark.anyio
async def test_completion_backward_compatibility():
    """Test that completion works without context (backward compatibility)."""
    context_was_none = False

    async def handle_completion(ctx: ServerRequestContext, params: CompleteRequestParams) -> CompleteResult:
        nonlocal context_was_none
        context_was_none = params.context is None
        return CompleteResult(completion=Completion(values=["no-context-completion"], total=1, has_more=False))

    server = Server("test-server", on_completion=handle_completion)

    async with Client(server) as client:
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

    async def handle_completion(ctx: ServerRequestContext, params: CompleteRequestParams) -> CompleteResult:
        # Simulate database/table completion scenario
        if isinstance(params.ref, ResourceTemplateReference):
            if params.ref.uri == "db://{database}/{table}":
                if params.argument.name == "database":
                    return CompleteResult(
                        completion=Completion(
                            values=["users_db", "products_db", "analytics_db"], total=3, has_more=False
                        )
                    )
                elif params.argument.name == "table":
                    if params.context and params.context.arguments:
                        db = params.context.arguments.get("database")
                        if db == "users_db":
                            return CompleteResult(
                                completion=Completion(
                                    values=["users", "sessions", "permissions"], total=3, has_more=False
                                )
                            )
                        elif db == "products_db":
                            return CompleteResult(
                                completion=Completion(
                                    values=["products", "categories", "inventory"], total=3, has_more=False
                                )
                            )

        pytest.fail("Unexpected completion request")

    server = Server("test-server", on_completion=handle_completion)

    async with Client(server) as client:
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

    async def handle_completion(ctx: ServerRequestContext, params: CompleteRequestParams) -> CompleteResult:
        if isinstance(params.ref, ResourceTemplateReference):
            if params.ref.uri == "db://{database}/{table}":
                if params.argument.name == "table":
                    if not params.context or not params.context.arguments or "database" not in params.context.arguments:
                        raise ValueError("Please select a database first to see available tables")
                    db = params.context.arguments.get("database")
                    if db == "test_db":
                        return CompleteResult(
                            completion=Completion(values=["users", "orders", "products"], total=3, has_more=False)
                        )

        pytest.fail("Unexpected completion request")

    server = Server("test-server", on_completion=handle_completion)

    async with Client(server) as client:
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
