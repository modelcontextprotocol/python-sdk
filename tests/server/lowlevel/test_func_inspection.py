"""Unit tests for func_inspection module.

Tests the create_call_wrapper function which determines how to call handler functions
with different parameter signatures and type hints.
"""

from typing import Any, Generic, TypeVar

import pytest

from mcp.server.lowlevel.func_inspection import create_call_wrapper
from mcp.types import ListPromptsRequest, ListResourcesRequest, ListToolsRequest, PaginatedRequestParams

T = TypeVar("T")


@pytest.mark.anyio
async def test_no_params_returns_deprecated_wrapper() -> None:
    """Test: def foo() - should call without request."""
    called_without_request = False

    async def handler() -> list[str]:
        nonlocal called_without_request
        called_without_request = True
        return ["test"]

    wrapper = create_call_wrapper(handler, ListPromptsRequest)

    # Wrapper should call handler without passing request
    request = ListPromptsRequest(method="prompts/list", params=None)
    result = await wrapper(request)
    assert called_without_request is True
    assert result == ["test"]


@pytest.mark.anyio
async def test_param_with_default_returns_deprecated_wrapper() -> None:
    """Test: def foo(thing: int = 1) - should call without request."""
    called_without_request = False

    async def handler(thing: int = 1) -> list[str]:
        nonlocal called_without_request
        called_without_request = True
        return [f"test-{thing}"]

    wrapper = create_call_wrapper(handler, ListPromptsRequest)

    # Wrapper should call handler without passing request (uses default value)
    request = ListPromptsRequest(method="prompts/list", params=None)
    result = await wrapper(request)
    assert called_without_request is True
    assert result == ["test-1"]


@pytest.mark.anyio
async def test_typed_request_param_passes_request() -> None:
    """Test: def foo(req: ListPromptsRequest) - should pass request through."""
    received_request = None

    async def handler(req: ListPromptsRequest) -> list[str]:
        nonlocal received_request
        received_request = req
        return ["test"]

    wrapper = create_call_wrapper(handler, ListPromptsRequest)

    # Wrapper should pass request to handler
    request = ListPromptsRequest(method="prompts/list", params=PaginatedRequestParams(cursor="test-cursor"))
    await wrapper(request)

    assert received_request is not None
    assert received_request is request
    params = getattr(received_request, "params", None)
    assert params is not None
    assert params.cursor == "test-cursor"


@pytest.mark.anyio
async def test_typed_request_with_default_param_passes_request() -> None:
    """Test: def foo(req: ListPromptsRequest, thing: int = 1) - should pass request through."""
    received_request = None
    received_thing = None

    async def handler(req: ListPromptsRequest, thing: int = 1) -> list[str]:
        nonlocal received_request, received_thing
        received_request = req
        received_thing = thing
        return ["test"]

    wrapper = create_call_wrapper(handler, ListPromptsRequest)

    # Wrapper should pass request to handler
    request = ListPromptsRequest(method="prompts/list", params=None)
    await wrapper(request)

    assert received_request is request
    assert received_thing == 1  # default value


@pytest.mark.anyio
async def test_optional_typed_request_with_default_none_is_deprecated() -> None:
    """Test: def foo(thing: int = 1, req: ListPromptsRequest | None = None) - old style."""
    called_without_request = False

    async def handler(thing: int = 1, req: ListPromptsRequest | None = None) -> list[str]:
        nonlocal called_without_request
        called_without_request = True
        return ["test"]

    wrapper = create_call_wrapper(handler, ListPromptsRequest)

    # Wrapper should call handler without passing request
    request = ListPromptsRequest(method="prompts/list", params=None)
    result = await wrapper(request)
    assert called_without_request is True
    assert result == ["test"]


@pytest.mark.anyio
async def test_untyped_request_param_is_deprecated() -> None:
    """Test: def foo(req) - should call without request."""
    called = False

    async def handler(req):  # type: ignore[no-untyped-def]  # pyright: ignore[reportMissingParameterType]
        nonlocal called
        called = True
        return ["test"]

    wrapper = create_call_wrapper(handler, ListPromptsRequest)  # pyright: ignore[reportUnknownArgumentType]

    # Wrapper should call handler without passing request, which will fail because req is required
    request = ListPromptsRequest(method="prompts/list", params=None)
    # This will raise TypeError because handler expects 'req' but wrapper doesn't provide it
    with pytest.raises(TypeError, match="missing 1 required positional argument"):
        await wrapper(request)


@pytest.mark.anyio
async def test_any_typed_request_param_is_deprecated() -> None:
    """Test: def foo(req: Any) - should call without request."""

    async def handler(req: Any) -> list[str]:
        return ["test"]

    wrapper = create_call_wrapper(handler, ListPromptsRequest)

    # Wrapper should call handler without passing request, which will fail because req is required
    request = ListPromptsRequest(method="prompts/list", params=None)
    # This will raise TypeError because handler expects 'req' but wrapper doesn't provide it
    with pytest.raises(TypeError, match="missing 1 required positional argument"):
        await wrapper(request)


@pytest.mark.anyio
async def test_generic_typed_request_param_is_deprecated() -> None:
    """Test: def foo(req: Generic[T]) - should call without request."""

    async def handler(req: Generic[T]) -> list[str]:  # pyright: ignore[reportGeneralTypeIssues]
        return ["test"]

    wrapper = create_call_wrapper(handler, ListPromptsRequest)

    # Wrapper should call handler without passing request, which will fail because req is required
    request = ListPromptsRequest(method="prompts/list", params=None)
    # This will raise TypeError because handler expects 'req' but wrapper doesn't provide it
    with pytest.raises(TypeError, match="missing 1 required positional argument"):
        await wrapper(request)


@pytest.mark.anyio
async def test_wrong_typed_request_param_is_deprecated() -> None:
    """Test: def foo(req: str) - should call without request."""

    async def handler(req: str) -> list[str]:
        return ["test"]

    wrapper = create_call_wrapper(handler, ListPromptsRequest)

    # Wrapper should call handler without passing request, which will fail because req is required
    request = ListPromptsRequest(method="prompts/list", params=None)
    # This will raise TypeError because handler expects 'req' but wrapper doesn't provide it
    with pytest.raises(TypeError, match="missing 1 required positional argument"):
        await wrapper(request)


@pytest.mark.anyio
async def test_required_param_before_typed_request_attempts_to_pass() -> None:
    """Test: def foo(thing: int, req: ListPromptsRequest) - attempts to pass request (will fail at runtime)."""
    received_request = None

    async def handler(thing: int, req: ListPromptsRequest) -> list[str]:
        nonlocal received_request
        received_request = req
        return ["test"]

    wrapper = create_call_wrapper(handler, ListPromptsRequest)

    # Wrapper will attempt to pass request, but it will fail at runtime
    # because 'thing' is required and has no default
    request = ListPromptsRequest(method="prompts/list", params=None)

    # This will raise TypeError because 'thing' is missing
    with pytest.raises(TypeError, match="missing 1 required positional argument: 'thing'"):
        await wrapper(request)


@pytest.mark.anyio
async def test_positional_only_param_with_correct_type() -> None:
    """Test: def foo(req: ListPromptsRequest, /) - should pass request through."""
    received_request = None

    async def handler(req: ListPromptsRequest, /) -> list[str]:
        nonlocal received_request
        received_request = req
        return ["test"]

    wrapper = create_call_wrapper(handler, ListPromptsRequest)

    # Wrapper should pass request to handler
    request = ListPromptsRequest(method="prompts/list", params=None)
    await wrapper(request)

    assert received_request is request


@pytest.mark.anyio
async def test_keyword_only_param_with_correct_type() -> None:
    """Test: def foo(*, req: ListPromptsRequest) - should pass request through."""
    received_request = None

    async def handler(*, req: ListPromptsRequest) -> list[str]:
        nonlocal received_request
        received_request = req
        return ["test"]

    wrapper = create_call_wrapper(handler, ListPromptsRequest)

    # Wrapper should pass request to handler with keyword argument
    request = ListPromptsRequest(method="prompts/list", params=None)
    await wrapper(request)

    assert received_request is request


@pytest.mark.anyio
async def test_different_request_types() -> None:
    """Test that wrapper works with different request types."""
    # Test with ListResourcesRequest
    received_request = None

    async def handler(req: ListResourcesRequest) -> list[str]:
        nonlocal received_request
        received_request = req
        return ["test"]

    wrapper = create_call_wrapper(handler, ListResourcesRequest)

    request = ListResourcesRequest(method="resources/list", params=None)
    await wrapper(request)

    assert received_request is request

    # Test with ListToolsRequest
    received_request = None

    async def handler2(req: ListToolsRequest) -> list[str]:
        nonlocal received_request
        received_request = req
        return ["test"]

    wrapper2 = create_call_wrapper(handler2, ListToolsRequest)

    request2 = ListToolsRequest(method="tools/list", params=None)
    await wrapper2(request2)

    assert received_request is request2


@pytest.mark.anyio
async def test_mixed_params_with_typed_request() -> None:
    """Test: def foo(a: str, req: ListPromptsRequest, b: int = 5) - attempts to pass request."""

    async def handler(a: str, req: ListPromptsRequest, b: int = 5) -> list[str]:
        return ["test"]

    wrapper = create_call_wrapper(handler, ListPromptsRequest)

    # Will fail at runtime due to missing 'a'
    request = ListPromptsRequest(method="prompts/list", params=None)

    with pytest.raises(TypeError, match="missing 1 required positional argument: 'a'"):
        await wrapper(request)
