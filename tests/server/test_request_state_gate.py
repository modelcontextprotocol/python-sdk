"""Startup gate for `request_state_security=` on MCP-server registration funnels
(`mcp.server.request_state` + the `MCPServer` wiring).

Every test here is synchronous registration-time behavior: no Client, no
connection, no event loop. The gate is SDK-defined product policy, deliberately
stricter than the spec's conditional MUST (basic/patterns/mrtr, server
requirements 4-5 apply only when state influences authorization, resource
access, or business logic): the SDK cannot see what authors put in their state,
so every MRTR-capable registration must pick a `RequestStateSecurity` posture
up front, before any client can connect.
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

# Registration fixtures. Only their signatures are inspected at registration; none
# is ever called, so each body is a bare `...` (a constant statement the compiler
# eliminates - nothing for coverage to miss, and pyright treats them as stubs).


# Resolver for `Resolve(...)` markers:
async def _provide_login(ctx: Context) -> str: ...


# Resolver-driven tool (RESOLVER capability):
async def _deploy(target: str, login: Annotated[str, Resolve(_provide_login)]) -> str: ...


# Manual-MRTR tool, prompt, and resource template (DECLARED_MANUAL capability):
async def _confirm_deploy(target: str) -> str | InputRequiredResult: ...


async def _briefing(topic: str) -> str | InputRequiredResult: ...


async def _record(id: str) -> str | InputRequiredResult: ...


# MRTR-free tool, prompt, static resource, and resource template:
async def _plain_tool(x: int) -> str: ...


async def _plain_prompt() -> str: ...


async def _plain_static() -> str: ...


async def _plain_template(id: str) -> str: ...


def test_resolver_tool_without_security_is_rejected_at_the_decorator_call() -> None:
    """SDK-defined product bar (stricter than the spec's conditional MUST, mrtr server
    reqs 4-5): a `Resolve(...)` tool mints requestState, so registering it on a server
    constructed without `request_state_security=` raises at the `@mcp.tool()` call with
    the full teaching text."""
    mcp = MCPServer("gate")

    with pytest.raises(ValueError) as excinfo:
        mcp.tool(name="deploy")(_deploy)

    assert str(excinfo.value) == snapshot("""\
Tool 'deploy' uses Resolve(...) parameters, so this server mints a
requestState that round-trips through the client. The MCP spec requires that state
to be integrity-protected, and rejected when verification fails, whenever it can
influence authorization, resource access, or business logic. Configure protection:

    MCPServer(..., request_state_security=RequestStateSecurity(keys=[key]))
        One or more shared secret keys (>= 32 bytes each). Required when a retry
        can reach a different instance (multi-worker or load-balanced HTTP).
        keys[0] seals, every key verifies; rotation is
        [old, new] -> [new, old] -> [new], each phase fully rolled out first.

    MCPServer(..., request_state_security=RequestStateSecurity.ephemeral())
        A key generated at process start. Single-process deployments only
        (stdio, one HTTP worker): state minted before a restart, or by another
        instance, is rejected and the client must restart the flow.

    MCPServer(..., request_state_security=RequestStateSecurity.unprotected())
        No protection. Only valid when tampering can cause nothing worse than a
        failed request - not available for Resolve(...) tools, whose state
        carries elicited answers.

Spec: https://modelcontextprotocol.io/specification/draft/basic/patterns/mrtr\
""")


def test_constructor_supplied_resolver_tool_bypasses_add_tool_but_is_still_rejected() -> None:
    """SDK-defined: `MCPServer(tools=[...])` inserts Tool objects directly into the
    ToolManager without going through `add_tool`, so `__init__` must re-scan and reject
    an unprotected resolver tool at construction, naming it."""
    tool = Tool.from_function(_deploy, name="deploy")

    with pytest.raises(ValueError) as excinfo:
        MCPServer("gate", tools=[tool])

    assert "deploy" in str(excinfo.value)


def test_constructor_supplied_declared_manual_tool_is_rejected() -> None:
    """SDK-defined: the constructor scan also derives DECLARED_MANUAL — a hand-supplied
    Tool whose function declares an InputRequiredResult return is rejected at
    `MCPServer(tools=[...])`, naming it."""
    with pytest.raises(ValueError) as excinfo:
        MCPServer("gate", tools=[Tool.from_function(_confirm_deploy, name="confirm_deploy")])

    assert "confirm_deploy" in str(excinfo.value)
    assert "declares an InputRequiredResult return" in str(excinfo.value)


def test_constructor_scan_trusts_the_tools_stored_resolver_authority() -> None:
    """SDK-defined: the constructor scan judges a hand-built Tool by its stored
    `resolved_params` — the authority that actually drives resolution at call time —
    not by re-inspecting `fn`, which a hand-built Tool may carry without any resolver
    annotations."""
    tool = Tool.from_function(_deploy, name="deploy").model_copy(update={"fn": _plain_tool})

    with pytest.raises(ValueError) as excinfo:
        MCPServer("gate", tools=[tool])

    assert "uses Resolve(...) parameters" in str(excinfo.value)


def test_constructor_scan_does_not_defer_a_hand_built_combo_tool() -> None:
    """SDK-defined: the decorator gate stands aside for a Resolve+InputRequiredResult
    combination because `Tool.from_function` rejects it with its own error; a hand-built
    Tool has no such backstop, so the constructor scan gates the combo as RESOLVER
    (stored `resolved_params` decide) instead of silently admitting it."""
    tool = Tool.from_function(_deploy, name="combo").model_copy(update={"fn": _confirm_deploy})

    with pytest.raises(ValueError) as excinfo:
        MCPServer("gate", tools=[tool])

    assert "uses Resolve(...) parameters" in str(excinfo.value)


def test_declared_manual_tool_without_security_is_rejected_naming_the_declared_return() -> None:
    """SDK-defined: a tool annotated `-> str | InputRequiredResult` (manual MRTR, no
    Resolve) also mints requestState, so unconfigured registration raises with the
    DECLARED_MANUAL variant text naming the declared return."""
    mcp = MCPServer("gate")

    with pytest.raises(ValueError) as excinfo:
        mcp.tool(name="confirm_deploy")(_confirm_deploy)

    assert str(excinfo.value) == snapshot("""\
Tool 'confirm_deploy' declares an InputRequiredResult return, so this server mints a
requestState that round-trips through the client. The MCP spec requires that state
to be integrity-protected, and rejected when verification fails, whenever it can
influence authorization, resource access, or business logic. Configure protection:

    MCPServer(..., request_state_security=RequestStateSecurity(keys=[key]))
        One or more shared secret keys (>= 32 bytes each). Required when a retry
        can reach a different instance (multi-worker or load-balanced HTTP).
        keys[0] seals, every key verifies; rotation is
        [old, new] -> [new, old] -> [new], each phase fully rolled out first.

    MCPServer(..., request_state_security=RequestStateSecurity.ephemeral())
        A key generated at process start. Single-process deployments only
        (stdio, one HTTP worker): state minted before a restart, or by another
        instance, is rejected and the client must restart the flow.

    MCPServer(..., request_state_security=RequestStateSecurity.unprotected())
        No protection. Only valid when tampering can cause nothing worse than a
        failed request - not available for Resolve(...) tools, whose state
        carries elicited answers.

Spec: https://modelcontextprotocol.io/specification/draft/basic/patterns/mrtr\
""")


def test_declared_manual_prompt_without_security_is_rejected_at_the_decorator_call() -> None:
    """SDK-defined: prompts/get is an MRTR carrier too, so a prompt function declaring
    `-> str | InputRequiredResult` is rejected at `@mcp.prompt()` on an unconfigured
    server."""
    mcp = MCPServer("gate")

    with pytest.raises(ValueError) as excinfo:
        mcp.prompt(name="briefing")(_briefing)

    assert str(excinfo.value) == snapshot("""\
Prompt 'briefing' declares an InputRequiredResult return, so this server mints a
requestState that round-trips through the client. The MCP spec requires that state
to be integrity-protected, and rejected when verification fails, whenever it can
influence authorization, resource access, or business logic. Configure protection:

    MCPServer(..., request_state_security=RequestStateSecurity(keys=[key]))
        One or more shared secret keys (>= 32 bytes each). Required when a retry
        can reach a different instance (multi-worker or load-balanced HTTP).
        keys[0] seals, every key verifies; rotation is
        [old, new] -> [new, old] -> [new], each phase fully rolled out first.

    MCPServer(..., request_state_security=RequestStateSecurity.ephemeral())
        A key generated at process start. Single-process deployments only
        (stdio, one HTTP worker): state minted before a restart, or by another
        instance, is rejected and the client must restart the flow.

    MCPServer(..., request_state_security=RequestStateSecurity.unprotected())
        No protection. Only valid when tampering can cause nothing worse than a
        failed request - not available for Resolve(...) tools, whose state
        carries elicited answers.

Spec: https://modelcontextprotocol.io/specification/draft/basic/patterns/mrtr\
""")


def test_declared_manual_prompt_via_add_prompt_is_rejected_the_same_way() -> None:
    """SDK-defined: `add_prompt(Prompt.from_function(...))` is the same funnel the
    decorator uses, so it trips the same gate and names the prompt."""
    mcp = MCPServer("gate")

    with pytest.raises(ValueError) as excinfo:
        mcp.add_prompt(Prompt.from_function(_briefing, name="briefing"))

    assert "briefing" in str(excinfo.value)


def test_declared_manual_resource_template_without_security_is_rejected_at_the_decorator_call() -> None:
    """SDK-defined: resources/read is an MRTR carrier for templates, so a template
    function declaring `-> str | InputRequiredResult` is rejected at
    `@mcp.resource("data://{id}")` on an unconfigured server."""
    mcp = MCPServer("gate")

    with pytest.raises(ValueError) as excinfo:
        mcp.resource("data://{id}")(_record)

    assert str(excinfo.value) == snapshot("""\
Resource template 'data://{id}' declares an InputRequiredResult return, so this server mints a
requestState that round-trips through the client. The MCP spec requires that state
to be integrity-protected, and rejected when verification fails, whenever it can
influence authorization, resource access, or business logic. Configure protection:

    MCPServer(..., request_state_security=RequestStateSecurity(keys=[key]))
        One or more shared secret keys (>= 32 bytes each). Required when a retry
        can reach a different instance (multi-worker or load-balanced HTTP).
        keys[0] seals, every key verifies; rotation is
        [old, new] -> [new, old] -> [new], each phase fully rolled out first.

    MCPServer(..., request_state_security=RequestStateSecurity.ephemeral())
        A key generated at process start. Single-process deployments only
        (stdio, one HTTP worker): state minted before a restart, or by another
        instance, is rejected and the client must restart the flow.

    MCPServer(..., request_state_security=RequestStateSecurity.unprotected())
        No protection. Only valid when tampering can cause nothing worse than a
        failed request - not available for Resolve(...) tools, whose state
        carries elicited answers.

Spec: https://modelcontextprotocol.io/specification/draft/basic/patterns/mrtr\
""")


def test_every_mrtr_surface_registers_cleanly_once_security_is_configured() -> None:
    """SDK-defined: with `request_state_security=` supplied, the exact registrations
    the gate rejects all succeed across every funnel (constructor `tools=`, tool and
    prompt and resource decorators, `add_prompt`)."""
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


def test_unprotected_refuses_resolver_tools_at_registration() -> None:
    """SDK-defined: `unprotected()` is not a lawful opt-out for `Resolve(...)` tools —
    their state carries elicited answers, which are business inputs — so registration
    still raises, with text pointing at `keys=`/`ephemeral()`."""
    mcp = MCPServer("gate", request_state_security=RequestStateSecurity.unprotected())

    with pytest.raises(ValueError) as excinfo:
        mcp.tool(name="deploy")(_deploy)

    assert str(excinfo.value) == snapshot("""\
Tool 'deploy' uses Resolve(...) parameters, so this server mints a
requestState that round-trips through the client. The MCP spec requires that state
to be integrity-protected, and rejected when verification fails, whenever it can
influence authorization, resource access, or business logic. Configure protection:

    MCPServer(..., request_state_security=RequestStateSecurity(keys=[key]))
        One or more shared secret keys (>= 32 bytes each). Required when a retry
        can reach a different instance (multi-worker or load-balanced HTTP).
        keys[0] seals, every key verifies; rotation is
        [old, new] -> [new, old] -> [new], each phase fully rolled out first.

    MCPServer(..., request_state_security=RequestStateSecurity.ephemeral())
        A key generated at process start. Single-process deployments only
        (stdio, one HTTP worker): state minted before a restart, or by another
        instance, is rejected and the client must restart the flow.

    Resolve(...) tools cannot opt out: their requestState carries elicited
    answers, which are business inputs. Use keys=[...] or .ephemeral().

Spec: https://modelcontextprotocol.io/specification/draft/basic/patterns/mrtr\
""")


def test_unprotected_is_a_lawful_opt_out_for_declared_manual_tools() -> None:
    """SDK-defined: a manual `-> str | InputRequiredResult` flow may hold state the
    spec's exception covers (tampering can cause nothing worse than request failure),
    so `unprotected()` lets it register; the author has explicitly accepted the risk."""
    mcp = MCPServer("gate", request_state_security=RequestStateSecurity.unprotected())

    mcp.tool(name="confirm_deploy")(_confirm_deploy)

    assert mcp._tool_manager.get_tool("confirm_deploy") is not None


def test_mrtr_free_registrations_need_no_security_configuration() -> None:
    """SDK-defined: the gate keys on MRTR capability, so plain tools (decorator and
    constructor-supplied), prompts, and resources register on an unconfigured server
    exactly as before — this pins the gate against over-firing."""
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
    """SDK-defined: configuring `request_state_security=` on a server that registers
    no MRTR-capable surface is legal — the policy sits inert rather than demanding
    MRTR usage."""
    mcp = MCPServer("gate", request_state_security=RequestStateSecurity.ephemeral())

    mcp.tool(name="plain_tool")(_plain_tool)

    assert mcp._tool_manager.get_tool("plain_tool") is not None


def test_lowlevel_server_has_no_gate_and_takes_the_boundary_as_ordinary_middleware() -> None:
    """SDK-defined: the lowlevel tier cannot see MRTR capability (handlers are opaque
    callables), so `Server` accepts an input_required-returning handler freely and
    protection is explicit — appending a `RequestStateBoundary` to `Server.middleware`
    grows the chain by one."""

    # Handler fixture: lowlevel registration neither inspects nor runs it here.
    async def call_tool(
        ctx: ServerRequestContext[Any, Any], params: CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult: ...

    server = Server("lowlevel", on_call_tool=call_tool)
    baseline = len(server.middleware)

    server.middleware.append(RequestStateBoundary(RequestStateSecurity.ephemeral()))

    assert len(server.middleware) == baseline + 1


def test_extension_contributed_resolver_tool_is_gated_through_add_tool() -> None:
    """SDK-defined: extension tools register through `MCPServer.add_tool`, so an
    extension whose `tools()` yields a `Resolve(...)` tool trips the gate when the
    host server has no `request_state_security=`."""

    class ResolverExt(Extension):
        identifier = "com.example/resolver"

        def tools(self) -> list[ToolBinding]:
            return [ToolBinding(fn=_deploy, kwargs={"name": "deploy"})]

    with pytest.raises(ValueError) as excinfo:
        MCPServer("gate", extensions=[ResolverExt()])

    assert "deploy" in str(excinfo.value)


def test_the_gate_fires_in_the_synchronous_registration_frame_not_at_first_request() -> None:
    """SDK-defined: rejection happens at the registration call itself — this module
    creates no Client, opens no connection, and runs no event loop — and a rejected
    registration leaves the server usable for further registrations."""
    mcp = MCPServer("gate")

    with pytest.raises(ValueError):
        mcp.tool(name="deploy")(_deploy)

    mcp.tool(name="plain_tool")(_plain_tool)
    assert mcp._tool_manager.get_tool("plain_tool") is not None
