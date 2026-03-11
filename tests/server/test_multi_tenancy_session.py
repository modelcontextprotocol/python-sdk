"""Tests for multi-tenancy support in session and request context."""

import time

import anyio
import pytest

from mcp.server.auth.middleware.auth_context import auth_context_var, get_tenant_id
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.context import ServerRequestContext
from mcp.server.experimental.request_context import Experimental
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared._context import RequestContext
from mcp.shared.message import SessionMessage
from mcp.shared.session import BaseSession
from mcp.types import ServerCapabilities


@pytest.fixture
def init_options() -> InitializationOptions:
    """Create initialization options for testing."""
    return InitializationOptions(
        server_name="test-server",
        server_version="1.0.0",
        capabilities=ServerCapabilities(),
    )


def test_request_context_with_tenant_id():
    """Test RequestContext can hold tenant_id."""
    # Use type: ignore since we're testing the dataclass field, not session behavior
    ctx: RequestContext[BaseSession] = RequestContext(  # type: ignore[type-arg]
        session=None,  # type: ignore[arg-type]
        request_id="test-1",
        tenant_id="tenant-xyz",
    )
    assert ctx.tenant_id == "tenant-xyz"


def test_request_context_without_tenant_id():
    """Test RequestContext defaults tenant_id to None."""
    ctx: RequestContext[BaseSession] = RequestContext(  # type: ignore[type-arg]
        session=None,  # type: ignore[arg-type]
        request_id="test-1",
    )
    assert ctx.tenant_id is None


def test_server_request_context_with_tenant_id():
    """Test ServerRequestContext can hold tenant_id."""
    ctx = ServerRequestContext(
        session=None,  # type: ignore[arg-type]
        lifespan_context={},
        experimental=Experimental(
            task_metadata=None,
            _client_capabilities=None,
            _session=None,  # type: ignore[arg-type]
            _task_support=None,
        ),
        tenant_id="tenant-abc",
    )
    assert ctx.tenant_id == "tenant-abc"


def test_server_request_context_inherits_tenant_id_from_base():
    """Test ServerRequestContext inherits tenant_id behavior from RequestContext."""
    # Without tenant_id
    ctx_no_tenant = ServerRequestContext(
        session=None,  # type: ignore[arg-type]
        lifespan_context={},
        experimental=Experimental(
            task_metadata=None,
            _client_capabilities=None,
            _session=None,  # type: ignore[arg-type]
            _task_support=None,
        ),
    )
    assert ctx_no_tenant.tenant_id is None

    # With tenant_id
    ctx_with_tenant = ServerRequestContext(
        session=None,  # type: ignore[arg-type]
        lifespan_context={},
        experimental=Experimental(
            task_metadata=None,
            _client_capabilities=None,
            _session=None,  # type: ignore[arg-type]
            _task_support=None,
        ),
        tenant_id="my-tenant",
    )
    assert ctx_with_tenant.tenant_id == "my-tenant"


@pytest.mark.anyio
async def test_server_session_tenant_id_property(init_options: InitializationOptions):
    """Test ServerSession tenant_id property and setter."""
    server_to_client_send, server_to_client_recv = anyio.create_memory_object_stream[SessionMessage](1)
    client_to_server_send, client_to_server_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)

    async with server_to_client_send, server_to_client_recv, client_to_server_send, client_to_server_recv:
        async with ServerSession(
            client_to_server_recv,
            server_to_client_send,
            init_options,
        ) as session:
            # Default tenant_id is None
            assert session.tenant_id is None

            # Can set tenant_id
            session.tenant_id = "tenant-123"
            assert session.tenant_id == "tenant-123"

            # Can change tenant_id
            session.tenant_id = "tenant-456"
            assert session.tenant_id == "tenant-456"

            # Can reset to None
            session.tenant_id = None
            assert session.tenant_id is None


def test_get_tenant_id_from_auth_context():
    """Test get_tenant_id extracts tenant_id from auth context."""
    # No auth context
    assert get_tenant_id() is None

    # With auth context but no tenant
    access_token_no_tenant = AccessToken(
        token="token1",
        client_id="client1",
        scopes=["read"],
        expires_at=int(time.time()) + 3600,
    )
    user_no_tenant = AuthenticatedUser(access_token_no_tenant)
    token = auth_context_var.set(user_no_tenant)
    try:
        assert get_tenant_id() is None
    finally:
        auth_context_var.reset(token)

    # With auth context and tenant
    access_token_with_tenant = AccessToken(
        token="token2",
        client_id="client2",
        scopes=["read"],
        expires_at=int(time.time()) + 3600,
        tenant_id="tenant-xyz",
    )
    user_with_tenant = AuthenticatedUser(access_token_with_tenant)
    token = auth_context_var.set(user_with_tenant)
    try:
        assert get_tenant_id() == "tenant-xyz"
    finally:
        auth_context_var.reset(token)
