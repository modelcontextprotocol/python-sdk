# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedImport=false, reportUnusedVariable=false, reportMissingTypeArgument=false, reportUnknownParameterType=false
from __future__ import annotations

import pytest

from mcp.server.state.server import StatefulMCP, StatefulMCPContext
from mcp.server.state.types import ToolResultType


@pytest.fixture
def anyio_backend():
    # Run tests on asyncio only (no trio dependency required)
    return "asyncio"

@pytest.fixture
async def app_linear_machine() -> StatefulMCP:
    """
    Build a minimal, validation-friendly state machine:

        s0 (initial) --DEFAULT/dummy--> s1 --DEFAULT/dummy--> s2 (terminal)

    Notes:
    - Exactly one initial state (s0)
    - One reachable terminal state (s2)
    - No outgoing transitions from the terminal state (future validator will enforce this)
    - The referenced tool ("dummy") is registered in the native ToolManager
    """
    app = StatefulMCP(name="smoke")

    # Register a real tool (so future validation "tool exists" passes)
    @app.tool()
    async def dummy() -> str:
        return "ok"

    # Assert it is actually registered in the native manager
    # (future validator will do something like manager.get_tool(name))
    assert app._tool_manager.get_tool("dummy") is not None

    # Define the linear machine WITHOUT outgoing edges from the terminal state
    (
        app.statebuilder
            .define_state("s0", is_initial=True)
            .transition("s1").on_tool("dummy", result=ToolResultType.DEFAULT)
            .done()
            .define_state("s1")
            .transition("s2").on_tool("dummy", result=ToolResultType.DEFAULT)
            .done()
            .define_state("s2", is_terminal=True)
            .done()
    )

    # Build and wire (no transport needed)
    app._build_state_machine_once()
    app._init_stateful_managers_once()

    # Quick sanity: starting state
    sm = app._state_machine
    assert sm is not None and sm.current_state == "s0"

    return app
