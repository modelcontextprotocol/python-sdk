# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedImport=false, reportUnusedVariable=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeArgument=false, reportUnknownParameterType=false, reportAssignmentType=false

import asyncio

import pytest
from pytest import LogCaptureFixture

from mcp.types import TextContent
from mcp.server.fastmcp.server import Context
from mcp.server.state.machine.state_machine import InputSymbol
from mcp.server.state.server import StatefulMCP
from mcp.server.state.types import ToolResultType, PromptResultType


@pytest.mark.anyio
async def test_context_injected_on_effect(caplog: LogCaptureFixture):
    """Ensure that when a Context resolver is available, the Context is injected into the effect."""
    caplog.set_level("DEBUG")

    app = StatefulMCP(name="inject_ctx_prompt_effect")

    called = {}

    async def ctx_effect(ctx: Context) -> str:
        called["ctx"] = ctx
        return "ok"

    @app.tool()
    def t_test() -> str:
        return "ok"

    # sanity: tool is registered
    assert app._tool_manager.get_tool("t_test") is not None

    # minimal machine: s0 -> s1 (callback expects Context)
    (
        app.statebuilder
            .define_state("s0", is_initial=True)
            .transition("s1").on_tool("t_test", result=ToolResultType.SUCCESS, effect=ctx_effect)
    )

    app._build_state_machine_once()
    app._init_stateful_managers_once()

    sm = app._state_machine
    assert sm is not None

    sm.transition(InputSymbol.for_tool("t_test", ToolResultType.SUCCESS))

    for _ in range(10): # let the asyc t_trigger run
        if "ctx" in called:
            break
        await asyncio.sleep(0.01)

    assert "ctx" in called, "Callback should have been called"
    assert called["ctx"] is not None, "Context should have been injected"
    assert any("Injecting context parameter for target" in rec.message for rec in caplog.records)

@pytest.mark.anyio
async def test_context_injected_on_prompt(caplog: LogCaptureFixture):
    """Ensure that when a Context resolver is available, the Context is injected into the prompt."""
    caplog.set_level("DEBUG")

    app = StatefulMCP(name="inject_ctx_prompt_test")

    called = {}

    @app.prompt()
    def p_ctx(ctx: Context) -> str:
        called["ctx"] = ctx
        return "ok"

    # this does not trigger the prompt (native manager)
    assert app._prompt_manager.get_prompt("p_ctx") is not None

    # minimal machine: s0 -> s1 (callback expects Context)
    (
        app.statebuilder
            .define_state("s0", is_initial=True)
            .transition("s1").on_prompt("p_ctx", PromptResultType.SUCCESS)
    )

    app._build_state_machine_once()
    app._init_stateful_managers_once()

    sm = app._state_machine
    assert sm is not None

    # this does trigger the prompt (stateful manager)
    await app.get_prompt("p_ctx")

    assert called["ctx"] is not None, "Context should have been injected"



@pytest.mark.anyio
async def test_context_injected_on_tool(caplog: LogCaptureFixture):
    """Ensure that when a Context resolver is available, the Context is injected into the tool."""
    caplog.set_level("DEBUG")

    app = StatefulMCP(name="inject_ctx_tool_test")

    called = {}

    @app.tool()
    def t_ctx(ctx: Context) -> str:
        called["ctx"] = ctx
        return "ok"

    # this does not trigger the tool (native manager)
    assert app._tool_manager.get_tool("t_ctx") is not None

    # minimal machine: s0 -> s1 (callback expects Context)
    (
        app.statebuilder
            .define_state("s0", is_initial=True)
            .transition("s1").on_tool("t_ctx", ToolResultType.SUCCESS)
    )

    app._build_state_machine_once()
    app._init_stateful_managers_once()

    sm = app._state_machine
    assert sm is not None

    # this does trigger the tool (stateful manager)
    await app.call_tool("t_ctx", {})

    assert called["ctx"] is not None, "Context should have been injected"