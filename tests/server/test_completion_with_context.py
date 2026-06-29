"""Tests for completion handler with context functionality."""

import pytest
from mcp_types import (
    CompleteRequestParams,
    CompleteResult,
    Completion,
    PromptReference,
    ResourceTemplateReference,
)

from mcp import Client
from mcp.server import Server, ServerRequestContext


@pytest.mark.anyio
async def test_completion_handler_receives_context():
    received_params: CompleteRequestParams | None = None

    async def handle_completion(ctx: ServerRequestContext, params: CompleteRequestParams) -> CompleteResult:
        nonlocal received_params
        received_params = params
        return CompleteResult(completion=Completion(values=["test-completion"], total=1, has_more=False))

    server = Server("test-server", on_completion=handle_completion)

    async with Client(server) as client:
        result = await client.complete(
            ref=ResourceTemplateReference(type="ref/resource", uri="test://resource/{param}"),
            argument={"name": "param", "value": "test"},
            context_arguments={"previous": "value"},
        )

        assert received_params is not None
        assert received_params.context is not None
        assert received_params.context.arguments == {"previous": "value"}
        assert result.completion.values == ["test-completion"]


@pytest.mark.anyio
async def test_completion_backward_compatibility():
    context_was_none = False

    async def handle_completion(ctx: ServerRequestContext, params: CompleteRequestParams) -> CompleteResult:
        nonlocal context_was_none
        context_was_none = params.context is None
        return CompleteResult(completion=Completion(values=["no-context-completion"], total=1, has_more=False))

    server = Server("test-server", on_completion=handle_completion)

    async with Client(server) as client:
        result = await client.complete(
            ref=PromptReference(type="ref/prompt", name="test-prompt"), argument={"name": "arg", "value": "val"}
        )

        assert context_was_none
        assert result.completion.values == ["no-context-completion"]


@pytest.mark.anyio
async def test_dependent_completion_scenario():
    async def handle_completion(ctx: ServerRequestContext, params: CompleteRequestParams) -> CompleteResult:
        assert isinstance(params.ref, ResourceTemplateReference)
        assert params.ref.uri == "db://{database}/{table}"

        if params.argument.name == "database":
            return CompleteResult(
                completion=Completion(values=["users_db", "products_db", "analytics_db"], total=3, has_more=False)
            )

        assert params.argument.name == "table"
        assert params.context and params.context.arguments
        db = params.context.arguments.get("database")
        if db == "users_db":
            return CompleteResult(
                completion=Completion(values=["users", "sessions", "permissions"], total=3, has_more=False)
            )
        else:
            assert db == "products_db"
            return CompleteResult(
                completion=Completion(values=["products", "categories", "inventory"], total=3, has_more=False)
            )

    server = Server("test-server", on_completion=handle_completion)

    async with Client(server) as client:
        db_result = await client.complete(
            ref=ResourceTemplateReference(type="ref/resource", uri="db://{database}/{table}"),
            argument={"name": "database", "value": ""},
        )
        assert "users_db" in db_result.completion.values
        assert "products_db" in db_result.completion.values

        table_result = await client.complete(
            ref=ResourceTemplateReference(type="ref/resource", uri="db://{database}/{table}"),
            argument={"name": "table", "value": ""},
            context_arguments={"database": "users_db"},
        )
        assert table_result.completion.values == ["users", "sessions", "permissions"]

        table_result2 = await client.complete(
            ref=ResourceTemplateReference(type="ref/resource", uri="db://{database}/{table}"),
            argument={"name": "table", "value": ""},
            context_arguments={"database": "products_db"},
        )
        assert table_result2.completion.values == ["products", "categories", "inventory"]


@pytest.mark.anyio
async def test_completion_error_on_missing_context():
    async def handle_completion(ctx: ServerRequestContext, params: CompleteRequestParams) -> CompleteResult:
        assert isinstance(params.ref, ResourceTemplateReference)
        assert params.ref.uri == "db://{database}/{table}"
        assert params.argument.name == "table"

        if not params.context or not params.context.arguments or "database" not in params.context.arguments:
            raise ValueError("Please select a database first to see available tables")

        db = params.context.arguments.get("database")
        assert db == "test_db"
        return CompleteResult(completion=Completion(values=["users", "orders", "products"], total=3, has_more=False))

    server = Server("test-server", on_completion=handle_completion)

    async with Client(server, mode="legacy") as client:
        with pytest.raises(Exception) as exc_info:
            await client.complete(
                ref=ResourceTemplateReference(type="ref/resource", uri="db://{database}/{table}"),
                argument={"name": "table", "value": ""},
            )

        assert "Please select a database first" in str(exc_info.value)

        result_with_context = await client.complete(
            ref=ResourceTemplateReference(type="ref/resource", uri="db://{database}/{table}"),
            argument={"name": "table", "value": ""},
            context_arguments={"database": "test_db"},
        )

        assert result_with_context.completion.values == ["users", "orders", "products"]
