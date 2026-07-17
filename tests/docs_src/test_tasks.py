"""`docs/advanced/tasks.md`: every claim the page makes, proved against the real SDK."""

import pytest
from mcp_types import INVALID_PARAMS, METHOD_NOT_FOUND, MISSING_REQUIRED_CLIENT_CAPABILITY, TextContent

from docs_src.tasks import tutorial001, tutorial002, tutorial003
from mcp import Client, MCPError, TaskFailedError
from mcp.client import TasksExtension
from mcp.client.tasks import get_task
from mcp.server.mcpserver import MCPServer
from mcp.server.tasks import EXTENSION_ID, CreateTaskResult, Tasks
from mcp.shared.tasks import GetTaskResult

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_opting_in_advertises_the_capability() -> None:
    """tutorial001: `extensions=[Tasks()]` advertises `io.modelcontextprotocol/tasks`
    under `capabilities.extensions`."""
    async with Client(tutorial001.mcp) as client:
        assert client.server_capabilities.extensions == {"io.modelcontextprotocol/tasks": {}}


async def test_a_declaring_clients_call_really_is_augmented() -> None:
    """tutorial001: the server answers a declaring client's `tools/call` with a
    `CreateTaskResult` — proved by the session-level guard that refuses one unless
    `allow_claimed=True` is passed."""
    async with Client(tutorial001.mcp, extensions=[TasksExtension()]) as client:
        with pytest.raises(RuntimeError, match="allow_claimed=True"):
            await client.session.call_tool("bake", {"flavor": "lemon"})


async def test_transparent_polling_surfaces_only_the_final_result() -> None:
    """tutorial001: `client.call_tool` on a declaring client polls `tasks/get`
    internally and returns the ordinary `CallToolResult`; the contract does not change."""
    async with Client(tutorial001.mcp, extensions=[TasksExtension()]) as client:
        result = await client.call_tool("bake", {"flavor": "lemon"})
    assert result.content == [TextContent(type="text", text="One lemon cake, ready.")]


async def test_the_bakery_client_program_runs_as_shown(capsys: pytest.CaptureFixture[str]) -> None:
    """tutorial001: `main()` is the literal client program on the page; the printed
    content matches the page's comment."""
    await tutorial001.main()
    assert "One lemon cake, ready." in capsys.readouterr().out


async def test_a_non_declaring_client_is_never_augmented() -> None:
    """tutorial001 + the degradation paragraph: a modern client that did not declare
    the extension gets the plain `CallToolResult`, always."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("bake", {"flavor": "plain"})
    assert result.content == [TextContent(type="text", text="One plain cake, ready.")]
    assert result.meta is None


async def test_a_legacy_connection_never_sees_tasks() -> None:
    """tutorial001 + the degradation paragraph: a legacy handshake cannot carry the
    capability, so the same declaring client gets plain results on that wire."""
    async with Client(tutorial001.mcp, mode="legacy", extensions=[TasksExtension()]) as client:
        assert client.server_capabilities.extensions is None
        result = await client.call_tool("bake", {"flavor": "rye"})
    assert result.content == [TextContent(type="text", text="One rye cake, ready.")]


async def test_the_augment_predicate_scopes_augmentation_per_call() -> None:
    """tutorial002: `augment` selects per request — `transcode` becomes a task stamped
    with the configured `ttlMs`; `ping` passes through untouched for the same client."""
    async with Client(tutorial002.mcp, extensions=[TasksExtension()]) as client:
        created = await client.session.call_tool("transcode", {"clip": "intro"}, allow_claimed=True)
        assert isinstance(created, CreateTaskResult)
        plain = await client.session.call_tool("ping")

    assert created.status == "completed"
    assert created.ttl_ms == 60_000
    assert plain.content == [TextContent(type="text", text="pong")]


async def test_transparent_polling_resolves_the_augmented_transcode_call() -> None:
    """tutorial002: the high-level `call_tool` drives the `transcode` task to its
    final result while `ping` stays an ordinary round trip."""
    async with Client(tutorial002.mcp, extensions=[TasksExtension()]) as client:
        transcoded = await client.call_tool("transcode", {"clip": "intro"})
        pong = await client.call_tool("ping", {})
    assert transcoded.content == [TextContent(type="text", text="intro transcoded.")]
    assert pong.content == [TextContent(type="text", text="pong")]


async def test_the_manual_driving_program_runs_as_shown(capsys: pytest.CaptureFixture[str]) -> None:
    """tutorial003: `main()` gets the typed `CreateTaskResult` and polls `tasks/get`
    itself; the three printed lines match the page's comments."""
    await tutorial003.main()
    out = capsys.readouterr().out
    assert "completed" in out
    assert "One mocha cake, ready." in out


async def test_a_failed_task_surfaces_as_task_failed_error() -> None:
    """The execution-model bullets: a JSON-RPC error during an augmented call records
    a `failed` task, and the transparent driver raises the typed `TaskFailedError`
    carrying the inlined error."""
    mcp = MCPServer("flaky", extensions=[Tasks()])

    @mcp.tool()
    def reject() -> str:
        """Always refuses."""
        raise MCPError(code=INVALID_PARAMS, message="bad input")

    async with Client(mcp, extensions=[TasksExtension()]) as client:
        with pytest.raises(TaskFailedError) as exc_info:
            await client.call_tool("reject", {})
    assert exc_info.value.code == INVALID_PARAMS
    assert exc_info.value.message == "bad input"


async def test_an_is_error_result_is_a_completed_task_not_a_failure() -> None:
    """The execution-model bullets: tool-level failure (`isError: true`) is a result,
    not a protocol error — the transparent driver returns it instead of raising."""
    mcp = MCPServer("flaky", extensions=[Tasks()])

    @mcp.tool()
    def stumble() -> str:
        """Always trips over itself."""
        raise ValueError("tripped")

    async with Client(mcp, extensions=[TasksExtension()]) as client:
        result = await client.call_tool("stumble", {})
    assert result.is_error is True


async def _get_task(client: Client, task_id: str) -> GetTaskResult:
    return await get_task(client.session, task_id)


async def test_tasks_methods_reject_a_non_declaring_modern_client_with_32021() -> None:
    """The who-sees-what table: `tasks/*` from a non-declaring modern client is
    `-32021` with the machine-readable `requiredCapabilities` payload."""
    async with Client(tutorial001.mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await _get_task(client, "task_anything")
    assert exc_info.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY
    assert exc_info.value.error.data == {"requiredCapabilities": {"extensions": {EXTENSION_ID: {}}}}


async def test_tasks_methods_do_not_exist_on_a_legacy_connection() -> None:
    """The who-sees-what table: SEP-2663 is not defined on the 2025-11-25 wire, so a
    legacy call gets `-32601` (method not found), never a capability error."""
    async with Client(tutorial001.mcp, mode="legacy", extensions=[TasksExtension()]) as client:
        with pytest.raises(MCPError) as exc_info:
            await _get_task(client, "task_anything")
    assert exc_info.value.code == METHOD_NOT_FOUND


async def test_an_unknown_or_expired_task_id_is_invalid_params() -> None:
    """The who-sees-what section: a declaring client naming an unknown (or expired —
    the store treats them identically) task id gets `-32602`."""
    async with Client(tutorial001.mcp, extensions=[TasksExtension()]) as client:
        with pytest.raises(MCPError) as exc_info:
            await _get_task(client, "task_does_not_exist")
    assert exc_info.value.code == INVALID_PARAMS
