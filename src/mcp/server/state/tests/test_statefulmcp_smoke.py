# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedImport=false, reportUnusedVariable=false

import pytest

from mcp.server.state.machine import InputSymbol
from mcp.server.state.types import ToolResultType
from mcp.server.state.server import StatefulMCP


# Run this to start the test:
# pytest -n 0 -o log_cli=true -o log_cli_level=INFO src\mcp\server\state\tests\test_statefulmcp_smoke.py

@pytest.mark.anyio
async def test_state_machine_linear_flow_until_terminal(app_linear_machine: StatefulMCP):
    """
    TODO: When auto-reset from terminal -> initial is implemented, assert that we return to "s0".
    """
    app = app_linear_machine
    sm = app._state_machine
    assert sm is not None
    assert sm.current_state == "s0"

    sm.transition(InputSymbol.for_tool("dummy", ToolResultType.SUCCESS))
    assert sm.current_state == "s1"

    sm.transition(InputSymbol.for_tool("dummy", ToolResultType.ERROR))
    assert sm.current_state == "s2"

    # TODO: once terminal auto-reset is implemented, replace with:
    # assert sm.current_state == "s0"

@pytest.mark.anyio
async def test_session_store(app_linear_machine: StatefulMCP):
    app = app_linear_machine

    # Session-scope: store is created on session init and usable
    sid = "test-session-1"
    await app._on_session_initialized(sid)
    assert sid in app._session_stores

    session_store = app._session_stores[sid]
    await session_store.aset("k_session", "v_session")
    assert (await session_store.aget("k_session")) == "v_session"


