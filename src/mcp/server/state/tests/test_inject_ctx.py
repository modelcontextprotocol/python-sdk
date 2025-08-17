# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedImport=false, reportUnusedVariable=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeArgument=false, reportUnknownParameterType=false

import asyncio

import pytest
from pytest import LogCaptureFixture

from mcp.server.fastmcp.server import Context
from mcp.server.state.machine.state_machine import InputSymbol
from mcp.server.state.server import StatefulMCP
from mcp.server.state.types import ToolResultType


@pytest.mark.anyio
async def test_context_injected_on_effect(caplog: LogCaptureFixture):
    """Ensure that when a Context resolver is available, the Context is injected into the callback."""
    caplog.set_level("DEBUG")

    app = StatefulMCP(name="ctx_inject_test")

    called = {}

    @app.tool()
    async def t_trigger(ctx: Context) -> str:
        called["ctx"] = ctx
        return "ok"

    # sanity: tool is registered
    assert app._tool_manager.get_tool("t_trigger") is not None

    # minimal machine: s0 -> s1 (callback expects Context)
    (
        app.statebuilder
            .define_state("s0", is_initial=True)
            .transition("s1").on_tool("t_trigger", result=ToolResultType.SUCCESS, effect=t_trigger)
    )

    app._build_state_machine_once()
    app._init_stateful_managers_once()

    sm = app._state_machine
    assert sm is not None

    sm.transition(InputSymbol.for_tool("t_trigger", ToolResultType.SUCCESS))

    for _ in range(10): # let the asyc t_trigger run
        if "ctx" in called:
            break
        await asyncio.sleep(0.01)

    assert "ctx" in called, "Callback should have been called"
    assert called["ctx"] is not None, "Context should have been injected"
    assert any("Injecting context parameter for target" in rec.message for rec in caplog.records)

