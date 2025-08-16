# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedImport=false, reportUnusedVariable=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeArgument=false, reportUnknownParameterType=false

from __future__ import annotations

import pytest

from mcp.server.state.server import StatefulMCP
from mcp.server.state.machine import InputSymbol
from mcp.server.state.types import ToolResultType

@pytest.fixture
async def app_branch_cycle_machine() -> StatefulMCP:
    """
    Build a branching/cyclic state machine:

        s0 (initial)
          ├─(t_login:SUCCESS)──> s1
          └─(t_alt:SUCCESS)────> sA

        s1
          ├─(t_next:SUCCESS)──> s2
          └─(t_abort:ERROR)───> sT (terminal)

        sA
          └─(t_merge:SUCCESS)─> s2

        s2
          ├─(t_back:SUCCESS)──> s1   (cycle)
          └─(t_finish:SUCCESS)> sT   (terminal)

        sT (terminal, no outgoing)

    Notes:
    - Exactly one initial state (s0)
    - At least one reachable terminal (sT)
    - Cyclic path between s1 and s2 via t_next / t_back
    """
    app = StatefulMCP(name="branch_cycle")

    # Register tools used by the machine
    @app.tool()
    async def t_login() -> str:
        return "ok"

    @app.tool()
    async def t_next() -> str:
        return "ok"

    @app.tool()
    async def t_back() -> str:
        return "ok"

    @app.tool()
    async def t_finish() -> str:
        return "ok"

    @app.tool()
    async def t_abort() -> str:
        return "ok"

    @app.tool()
    async def t_alt() -> str:
        return "ok"

    @app.tool()
    async def t_merge() -> str:
        return "ok"

    # Ensure tools are actually registered in native manager (sanity)
    for t in ("t_login", "t_next", "t_back", "t_finish", "t_abort", "t_alt", "t_merge"):
        assert app._tool_manager.get_tool(t) is not None

    # Define states & transitions
    (
        app.statebuilder
            # s0 initial
            .define_state("s0", is_initial=True)
            .transition("s1").on_tool("t_login", result=ToolResultType.SUCCESS)
            .transition("sA").on_tool("t_alt", result=ToolResultType.SUCCESS)
            .done()

            # s1
            .define_state("s1")
            .transition("s2").on_tool("t_next", result=ToolResultType.SUCCESS)
            .transition("sT").on_tool("t_abort", result=ToolResultType.ERROR)
            .done()

            # sA branch merging into s2
            .define_state("sA")
            .transition("s2").on_tool("t_merge", result=ToolResultType.SUCCESS)
            .done()

            # s2 with cycle back to s1 and terminal to sT
            .define_state("s2")
            .transition("s1").on_tool("t_back", result=ToolResultType.SUCCESS)
            .transition("sT").on_tool("t_finish", result=ToolResultType.SUCCESS)
            .done()

            # sT implicit terminal (no outgoing transitions)
            .define_state("sT", is_terminal=True)
            .done()
    )

    # Build (validation happens here)
    app._build_state_machine_once()
    app._init_stateful_managers_once()

    sm = app._state_machine
    assert sm is not None and sm.current_state == "s0"
    return app


@pytest.mark.anyio
async def test_path_A_cycle_then_terminal(app_branch_cycle_machine: StatefulMCP) -> None:
    """
    Path A:
      s0 --t_login/SUCCESS--> s1
      s1 --t_next/SUCCESS-->  s2
      s2 --t_back/SUCCESS-->  s1   (cycle)
      s1 --t_next/SUCCESS-->  s2
      s2 --t_finish/SUCCESS-> sT   (terminal) -> auto reset to s0
    """
    app = app_branch_cycle_machine
    sm = app._state_machine
    assert sm is not None and sm.current_state == "s0"

    sm.transition(InputSymbol.for_tool("t_login", ToolResultType.SUCCESS))
    assert sm.current_state == "s1"

    sm.transition(InputSymbol.for_tool("t_next", ToolResultType.SUCCESS))
    assert sm.current_state == "s2"

    sm.transition(InputSymbol.for_tool("t_back", ToolResultType.SUCCESS))
    assert sm.current_state == "s1"  # cycle back

    sm.transition(InputSymbol.for_tool("t_next", ToolResultType.SUCCESS))
    assert sm.current_state == "s2"

    sm.transition(InputSymbol.for_tool("t_finish", ToolResultType.SUCCESS))
    # sT is terminal → auto-reset
    assert sm.current_state == "s0"


@pytest.mark.anyio
async def test_path_B_branch_merge_then_terminal(app_branch_cycle_machine: StatefulMCP) -> None:
    """
    Path B:
      s0 --t_alt/SUCCESS-->   sA
      sA --t_merge/SUCCESS--> s2
      s2 --t_finish/SUCCESS-> sT (terminal) -> auto reset to s0
    """
    app = app_branch_cycle_machine
    sm = app._state_machine
    assert sm is not None and sm.current_state == "s0"

    sm.transition(InputSymbol.for_tool("t_alt", ToolResultType.SUCCESS))
    assert sm.current_state == "sA"

    sm.transition(InputSymbol.for_tool("t_merge", ToolResultType.SUCCESS))
    assert sm.current_state == "s2"

    sm.transition(InputSymbol.for_tool("t_finish", ToolResultType.SUCCESS))
    assert sm.current_state == "s0"  # reset after terminal


@pytest.mark.anyio
async def test_path_C_abort_from_s1_to_terminal(app_branch_cycle_machine: StatefulMCP) -> None:
    """
    Path C:
      s0 --t_login/SUCCESS--> s1
      s1 --t_abort/ERROR----> sT (terminal) -> auto reset to s0
    """
    app = app_branch_cycle_machine
    sm = app._state_machine
    assert sm is not None and sm.current_state == "s0"

    sm.transition(InputSymbol.for_tool("t_login", ToolResultType.SUCCESS))
    assert sm.current_state == "s1"

    sm.transition(InputSymbol.for_tool("t_abort", ToolResultType.ERROR))
    assert sm.current_state == "s0"  # reset after terminal
