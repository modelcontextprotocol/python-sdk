"""Tests for multi-tenancy support in session and request context."""

import time

import anyio
import pytest

from mcp import Client
from mcp.server import Server
from mcp.server.auth.middleware.auth_context import auth_context_var, get_tenant_id
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.context import ServerRequestContext
from mcp.server.experimental.request_context import Experimental
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared._context import RequestContext, tenant_id_var
from mcp.shared.message import SessionMessage
from mcp.shared.session import BaseSession
from mcp.types import ListToolsResult, NotificationParams, PaginatedRequestParams, ServerCapabilities


def _simulate_tenant_binding(session: ServerSession, tenant_id_value: str) -> None:
    """Simulate the set-once tenant binding logic from lowlevel/server.py.

    Sets both auth_context_var (as AuthContextMiddleware does) and tenant_id_var
    (the transport-agnostic contextvar that the server reads).
    """
    access_token = AccessToken(
        token=f"token-{tenant_id_value}",
        client_id="client",
        scopes=["read"],
        expires_at=int(time.time()) + 3600,
        tenant_id=tenant_id_value,
    )
    user = AuthenticatedUser(access_token)
    auth_token = auth_context_var.set(user)
    tenant_token = tenant_id_var.set(tenant_id_value)
    try:
        tenant_id = tenant_id_var.get()
        if tenant_id is not None and session.tenant_id is None:
            session.tenant_id = tenant_id
    finally:
        tenant_id_var.reset(tenant_token)
        auth_context_var.reset(auth_token)


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
    """Test ServerSession tenant_id property with set-once semantics."""
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

            # Setting to the same value is allowed
            session.tenant_id = "tenant-123"
            assert session.tenant_id == "tenant-123"

            # Cannot change to a different value
            with pytest.raises(ValueError, match="Cannot change tenant_id"):
                session.tenant_id = "tenant-456"

            # Cannot reset to None once set
            with pytest.raises(ValueError, match="Cannot change tenant_id"):
                session.tenant_id = None

            # Original value is preserved
            assert session.tenant_id == "tenant-123"


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


@pytest.mark.anyio
async def test_session_tenant_id_set_from_auth_context_on_first_request(init_options: InitializationOptions):
    """Verify session.tenant_id is populated from auth context on the first request.

    The lowlevel server sets session.tenant_id from get_tenant_id() on the
    first request that has a tenant. This test simulates that behavior directly.
    """
    server_to_client_send, server_to_client_recv = anyio.create_memory_object_stream[SessionMessage](1)
    client_to_server_send, client_to_server_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)

    async with server_to_client_send, server_to_client_recv, client_to_server_send, client_to_server_recv:
        async with ServerSession(
            client_to_server_recv,
            server_to_client_send,
            init_options,
        ) as session:
            assert session.tenant_id is None

            # Simulate what lowlevel/server.py does: set session.tenant_id
            # from auth context on first request
            _simulate_tenant_binding(session, "tenant-first")
            assert session.tenant_id == "tenant-first"

            # Simulate a second request with a different tenant —
            # session.tenant_id should NOT change (set-once on first request)
            _simulate_tenant_binding(session, "tenant-second")

            # Still the first tenant — not overwritten
            assert session.tenant_id == "tenant-first"


@pytest.mark.anyio
async def test_tenant_context_isolation_between_concurrent_requests():
    """Verify tenant_id doesn't leak between concurrent async contexts.

    This test validates a critical security property: when multiple requests
    from different tenants are processed concurrently, each request must only
    see its own tenant_id, never another tenant's.

    How it works:
    1. We simulate two concurrent requests, each with a different tenant_id
       ("tenant-A" and "tenant-B").

    2. Each simulated request:
       - Creates an AccessToken with its tenant_id
       - Sets it in the auth_context_var (the contextvar used for auth state)
       - Yields control via checkpoint() to allow the other task to run
       - Reads back the tenant_id via get_tenant_id()
       - Stores the result for verification

    3. The anyio.lowlevel.checkpoint() forces a context switch, creating
       an opportunity for tenant context to "leak" if the isolation is
       broken. Without proper contextvar isolation, task2 might see
       task1's tenant_id (or vice versa) after the context switch.

    4. We use anyio.create_task_group() to run both tasks truly concurrently,
       not sequentially. This is essential for testing isolation.

    5. Finally, we verify each request saw only its own tenant_id.

    If this test fails, it indicates a serious security issue where tenant
    data could leak between concurrent requests.
    """
    # Store results from each simulated request
    results: dict[str, str | None] = {}

    async def simulate_request(tenant_id: str, request_key: str) -> None:
        """Simulate a request with a specific tenant context.

        Args:
            tenant_id: The tenant_id to set in the auth context
            request_key: A key to identify this request's result
        """
        # Create an access token with the tenant_id, simulating what
        # the auth middleware does when a request comes in
        access_token = AccessToken(
            token=f"token-{request_key}",
            client_id="test-client",
            scopes=["read"],
            expires_at=int(time.time()) + 3600,
            tenant_id=tenant_id,
        )
        user = AuthenticatedUser(access_token)

        # Set both contextvars - this is what AuthContextMiddleware does
        auth_token = auth_context_var.set(user)
        tenant_token = tenant_id_var.set(tenant_id)
        try:
            # Yield control to allow other tasks to run. This is the critical
            # point where context leakage could occur if isolation is broken.
            await anyio.lowlevel.checkpoint()

            # Read back the tenant_id - should still be our tenant, not the other
            results[request_key] = tenant_id_var.get()
        finally:
            # Always reset the context (mirrors middleware behavior)
            tenant_id_var.reset(tenant_token)
            auth_context_var.reset(auth_token)

    # Run both requests concurrently using a task group
    async with anyio.create_task_group() as tg:
        tg.start_soon(simulate_request, "tenant-A", "request1")
        tg.start_soon(simulate_request, "tenant-B", "request2")

    # Verify isolation: each request should see only its own tenant_id
    assert results["request1"] == "tenant-A", "Request 1 saw wrong tenant_id"
    assert results["request2"] == "tenant-B", "Request 2 saw wrong tenant_id"


@pytest.mark.anyio
async def test_server_session_isolation_between_instances(init_options: InitializationOptions):
    """Verify tenant_id is isolated between separate ServerSession instances.

    This test ensures that setting tenant_id on one ServerSession does not
    affect another ServerSession instance. Each session should maintain its
    own independent tenant context.

    This is important for scenarios where a server handles multiple sessions
    concurrently - each session belongs to a specific tenant and must not
    see or affect other tenants' sessions.
    """
    # Create streams for two independent sessions
    send1, recv1 = anyio.create_memory_object_stream[SessionMessage](1)
    send2, recv2 = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    send3, recv3 = anyio.create_memory_object_stream[SessionMessage](1)
    send4, recv4 = anyio.create_memory_object_stream[SessionMessage | Exception](1)

    async with send1, recv1, send2, recv2, send3, recv3, send4, recv4:
        # Create two separate server sessions
        async with (
            ServerSession(recv2, send1, init_options) as session1,
            ServerSession(recv4, send3, init_options) as session2,
        ):
            # Set different tenant_ids on each session
            session1.tenant_id = "tenant-alpha"
            session2.tenant_id = "tenant-beta"

            # Verify each session maintains its own tenant_id
            assert session1.tenant_id == "tenant-alpha"
            assert session2.tenant_id == "tenant-beta"

            # Attempting to change one session's tenant_id raises
            with pytest.raises(ValueError, match="Cannot change tenant_id"):
                session1.tenant_id = "tenant-gamma"

            # Both sessions retain their original values
            assert session1.tenant_id == "tenant-alpha"
            assert session2.tenant_id == "tenant-beta"


@pytest.mark.anyio
async def test_handle_request_populates_session_tenant_id():
    """E2E: session.tenant_id is set from auth context during request handling.

    This exercises the set-once tenant binding in lowlevel/server.py
    _handle_request, covering the branch where get_tenant_id() returns
    a non-None value.
    """
    captured_ctx_tenant: str | None = None
    captured_session_tenant: str | None = None

    async def handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        nonlocal captured_ctx_tenant, captured_session_tenant
        captured_ctx_tenant = ctx.tenant_id
        captured_session_tenant = ctx.session.tenant_id
        return ListToolsResult(tools=[])

    server = Server("test", on_list_tools=handle_list_tools)

    # Set auth context with tenant before entering the Client —
    # contextvars are inherited by child tasks, so the server will see it
    access_token = AccessToken(
        token="test-token",
        client_id="test-client",
        scopes=["read"],
        expires_at=int(time.time()) + 3600,
        tenant_id="tenant-e2e",
    )
    user = AuthenticatedUser(access_token)
    auth_token = auth_context_var.set(user)
    tenant_token = tenant_id_var.set("tenant-e2e")
    try:
        async with Client(server) as client:
            await client.list_tools()
    finally:
        tenant_id_var.reset(tenant_token)
        auth_context_var.reset(auth_token)

    assert captured_ctx_tenant == "tenant-e2e"
    assert captured_session_tenant == "tenant-e2e"


@pytest.mark.anyio
async def test_handle_notification_populates_session_tenant_id():
    """E2E: session.tenant_id is set from auth context during notification handling.

    This exercises the set-once tenant binding in lowlevel/server.py
    _handle_notification, covering the branch where get_tenant_id() returns
    a non-None value.
    """
    notification_tenant: str | None = None
    notification_received = anyio.Event()

    async def handle_roots_list_changed(ctx: ServerRequestContext, params: NotificationParams | None) -> None:
        nonlocal notification_tenant
        notification_tenant = ctx.tenant_id
        notification_received.set()

    server = Server("test", on_roots_list_changed=handle_roots_list_changed)

    access_token = AccessToken(
        token="test-token",
        client_id="test-client",
        scopes=["read"],
        expires_at=int(time.time()) + 3600,
        tenant_id="tenant-notify",
    )
    user = AuthenticatedUser(access_token)
    auth_token = auth_context_var.set(user)
    tenant_token = tenant_id_var.set("tenant-notify")
    try:
        async with Client(server) as client:
            await client.session.send_roots_list_changed()
            with anyio.fail_after(5):
                await notification_received.wait()
    finally:
        tenant_id_var.reset(tenant_token)
        auth_context_var.reset(auth_token)

    assert notification_tenant == "tenant-notify"
