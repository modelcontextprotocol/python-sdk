"""Startup gate for `request_state_security=` on the MCP-server registration funnels.

Every test is synchronous registration-time behavior: no Client, no connection,
no event loop. The gate is resolver-only: a `Resolve(...)` tool's requestState
carries elicited answers, which the spec requires to be integrity-protected
(mrtr server requirements 4-5). Manual `InputRequiredResult` surfaces are not
gated; their author-written state passes through an unconfigured server as
plaintext (pinned by the boundary tests).
"""

from typing import Annotated, Any

import pytest
from inline_snapshot import snapshot
from mcp_types import CallToolRequestParams, CallToolResult, InputRequiredResult

from mcp.server import MCPServer, Server, ServerRequestContext
from mcp.server.extension import Extension, ToolBinding
from mcp.server.mcpserver import Context, Resolve
from mcp.server.mcpserver.prompts import Prompt
from mcp.server.mcpserver.tools import Tool
from mcp.server.request_state import RequestStateBoundary, RequestStateSecurity

# Registration fixtures: only their signatures are inspected and none is ever
# called, so each body is a bare `...` (nothing for coverage to miss).


# Resolver for `Resolve(...)` markers:
async def _provide_login(ctx: Context) -> str: ...


# Resolver-driven tool (the only gated capability):
async def _deploy(target: str, login: Annotated[str, Resolve(_provide_login)]) -> str: ...


# Manual-MRTR tool, prompt, and resource template (not gated):
async def _confirm_deploy(target: str) -> str | InputRequiredResult: ...


async def _briefing(topic: str) -> str | InputRequiredResult: ...


async def _record(id: str) -> str | InputRequiredResult: ...


# MRTR-free tool, prompt, static resource, and resource template:
async def _plain_tool(x: int) -> str: ...


async def _plain_prompt() -> str: ...


async def _plain_static() -> str: ...


async def _plain_template(id: str) -> str: ...


def test_resolver_tool_without_security_is_rejected_at_the_decorator_call() -> None:
    """SDK-defined: a `Resolve(...)` tool on a server without `request_state_security=`
    is rejected at the `@mcp.tool()` call with the full teaching text."""
    mcp = MCPServer("gate")

    with pytest.raises(ValueError) as excinfo:
        mcp.tool(name="deploy")(_deploy)

    assert str(excinfo.value) == snapshot("""\
Tool 'deploy' uses Resolve(...) parameters, so this server mints a
requestState carrying elicited answers that round-trips through the client. The
MCP spec requires that state to be integrity-protected, and rejected when
verification fails, whenever it can influence authorization, resource access,
or business logic. Configure protection:

    MCPServer(..., request_state_security=RequestStateSecurity(keys=[key]))
        One or more shared secret keys (>= 32 bytes each). Required when a retry
        can reach a different instance (multi-worker or load-balanced HTTP).
        keys[0] seals, every key verifies; rotation is
        [old, new] -> [new, old] -> [new], each phase fully rolled out first.

    MCPServer(..., request_state_security=RequestStateSecurity.ephemeral())
        A key generated at process start. Single-process deployments only
        (stdio, one HTTP worker): state minted before a restart, or by another
        instance, is rejected and the client must restart the flow.

For your own crypto (a KMS, an existing token service), pass
RequestStateSecurity(codec=...).

Spec: https://modelcontextprotocol.io/specification/draft/basic/patterns/mrtr\
""")


def test_constructor_supplied_resolver_tool_bypasses_add_tool_but_is_still_rejected() -> None:
    """SDK-defined: `MCPServer(tools=[...])` bypasses `add_tool`, so `__init__` re-scans and rejects, naming it."""
    tool = Tool.from_function(_deploy, name="deploy")

    with pytest.raises(ValueError) as excinfo:
        MCPServer("gate", tools=[tool])

    assert "deploy" in str(excinfo.value)


def test_constructor_scan_trusts_the_tools_stored_resolver_authority() -> None:
    """SDK-defined: the constructor scan judges a hand-built Tool by its stored `resolved_params`, not its fn."""
    tool = Tool.from_function(_deploy, name="deploy").model_copy(update={"fn": _plain_tool})

    with pytest.raises(ValueError) as excinfo:
        MCPServer("gate", tools=[tool])

    assert "uses Resolve(...) parameters" in str(excinfo.value)


def test_constructor_scan_does_not_defer_a_hand_built_combo_tool() -> None:
    """SDK-defined: a hand-built Tool whose `resolved_params` and fn disagree is judged by the stored authority."""
    tool = Tool.from_function(_deploy, name="combo").model_copy(update={"fn": _confirm_deploy})

    with pytest.raises(ValueError) as excinfo:
        MCPServer("gate", tools=[tool])

    assert "uses Resolve(...) parameters" in str(excinfo.value)


def test_decorator_combo_fn_on_an_unconfigured_server_raises_the_resolver_gate_error() -> None:
    """SDK-defined: the `add_tool` gate runs before `Tool.from_function`, so the combo fn raises the resolver error."""
    mcp = MCPServer("gate")

    async def combo(target: str, login: Annotated[str, Resolve(_provide_login)]) -> str | InputRequiredResult: ...

    with pytest.raises(ValueError) as excinfo:
        mcp.tool()(combo)

    assert "uses Resolve(...) parameters" in str(excinfo.value)


def test_declared_manual_surfaces_register_cleanly_on_an_unconfigured_server() -> None:
    """SDK-defined: declared manual surfaces are not gated; every funnel registers them on an unconfigured server."""
    mcp = MCPServer("gate", tools=[Tool.from_function(_confirm_deploy, name="ctor_confirm_deploy")])

    mcp.tool(name="confirm_deploy")(_confirm_deploy)
    mcp.prompt(name="briefing")(_briefing)
    mcp.add_prompt(Prompt.from_function(_briefing, name="briefing_via_add"))
    mcp.resource("data://{id}")(_record)

    assert mcp._tool_manager.get_tool("ctor_confirm_deploy") is not None
    assert mcp._tool_manager.get_tool("confirm_deploy") is not None
    assert mcp._prompt_manager.get_prompt("briefing") is not None
    assert mcp._prompt_manager.get_prompt("briefing_via_add") is not None
    assert [t.uri_template for t in mcp._resource_manager.list_templates()] == ["data://{id}"]


def test_every_mrtr_surface_registers_cleanly_once_security_is_configured() -> None:
    """SDK-defined: with `request_state_security=` supplied, every MRTR surface registers via every funnel."""
    mcp = MCPServer(
        "gate",
        request_state_security=RequestStateSecurity.ephemeral(),
        tools=[Tool.from_function(_deploy, name="deploy")],
    )
    mcp.tool(name="confirm_deploy")(_confirm_deploy)
    mcp.prompt(name="briefing")(_briefing)
    mcp.add_prompt(Prompt.from_function(_briefing, name="briefing_via_add"))
    mcp.resource("data://{id}")(_record)

    assert mcp._tool_manager.get_tool("deploy") is not None
    assert mcp._tool_manager.get_tool("confirm_deploy") is not None
    assert mcp._prompt_manager.get_prompt("briefing") is not None
    assert mcp._prompt_manager.get_prompt("briefing_via_add") is not None
    assert [t.uri_template for t in mcp._resource_manager.list_templates()] == ["data://{id}"]


def test_mrtr_free_registrations_need_no_security_configuration() -> None:
    """SDK-defined: the gate keys on `Resolve(...)` usage; MRTR-free registrations work exactly as before."""
    mcp = MCPServer("gate", tools=[Tool.from_function(_plain_tool, name="ctor_plain_tool")])

    mcp.tool(name="plain_tool")(_plain_tool)
    mcp.prompt(name="plain_prompt")(_plain_prompt)
    mcp.resource("data://static")(_plain_static)
    mcp.resource("plain://{id}")(_plain_template)

    assert mcp._tool_manager.get_tool("ctor_plain_tool") is not None
    assert mcp._tool_manager.get_tool("plain_tool") is not None
    assert mcp._prompt_manager.get_prompt("plain_prompt") is not None
    assert len(mcp._resource_manager.list_resources()) == 1
    assert len(mcp._resource_manager.list_templates()) == 1


def test_security_with_zero_mrtr_registrations_is_legal_and_inert() -> None:
    """SDK-defined: `request_state_security=` with no MRTR-capable registration is legal and inert."""
    mcp = MCPServer("gate", request_state_security=RequestStateSecurity.ephemeral())

    mcp.tool(name="plain_tool")(_plain_tool)

    assert mcp._tool_manager.get_tool("plain_tool") is not None


def test_lowlevel_server_has_no_gate_and_takes_the_boundary_as_ordinary_middleware() -> None:
    """SDK-defined: the lowlevel `Server` has no gate; protection is an explicit `RequestStateBoundary` middleware."""

    # Handler fixture: lowlevel registration neither inspects nor runs it here.
    async def call_tool(
        ctx: ServerRequestContext[Any, Any], params: CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult: ...

    server = Server("lowlevel", on_call_tool=call_tool)
    baseline = len(server.middleware)

    server.middleware.append(RequestStateBoundary(RequestStateSecurity.ephemeral(), default_audience=server.name))

    assert len(server.middleware) == baseline + 1


def test_extension_contributed_resolver_tool_is_gated_through_add_tool() -> None:
    """SDK-defined: extension tools register through `MCPServer.add_tool`, so the gate covers them."""

    class ResolverExt(Extension):
        identifier = "com.example/resolver"

        def tools(self) -> list[ToolBinding]:
            return [ToolBinding(fn=_deploy, kwargs={"name": "deploy"})]

    with pytest.raises(ValueError) as excinfo:
        MCPServer("gate", extensions=[ResolverExt()])

    assert "deploy" in str(excinfo.value)


def test_the_gate_fires_in_the_synchronous_registration_frame_not_at_first_request() -> None:
    """SDK-defined: rejection happens in the registration frame and leaves the server usable afterward."""
    mcp = MCPServer("gate")

    with pytest.raises(ValueError):
        mcp.tool(name="deploy")(_deploy)

    mcp.tool(name="plain_tool")(_plain_tool)
    assert mcp._tool_manager.get_tool("plain_tool") is not None


# -- audience requires a server identity ------------------------------------------------


@pytest.mark.parametrize("name", [None, ""], ids=["unnamed", "empty-string"])
def test_an_unnamed_server_with_security_must_name_itself_or_set_an_audience(name: str | None) -> None:
    """SDK-defined: `request_state_security=` without a real name raises; any falsy name
    would stamp the shared placeholder as the token audience."""
    with pytest.raises(ValueError) as excinfo:
        MCPServer(name, request_state_security=RequestStateSecurity.ephemeral())

    assert str(excinfo.value) == snapshot("""\
request_state_security is configured but this server has no name. Sealed
requestState carries the server name as an audience claim, so state minted by
another service that shares the same keys is rejected; unnamed servers would
all stamp the same placeholder and the check would mean nothing. Name the
server (MCPServer("my-service", ...)) or set RequestStateSecurity(audience=...).\
""")


def test_a_named_server_or_an_explicit_audience_satisfies_the_audience_requirement() -> None:
    """SDK-defined: naming the server or setting `RequestStateSecurity(audience=...)` both construct."""
    MCPServer("named", request_state_security=RequestStateSecurity.ephemeral())
    MCPServer(request_state_security=RequestStateSecurity.ephemeral(audience="svc"))
