# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedImport=false, reportUnusedVariable=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeArgument=false, reportUnknownParameterType=false

from __future__ import annotations

import pytest

from mcp.server.state.machine.state_machine import InputSymbol
from mcp.server.state.server import StatefulMCP
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

    # Define states & transitions (input-first DSL)
    (
        app.statebuilder
            # s0 initial
            .define_state("s0", is_initial=True)
                .on_tool("t_login").on_success("s1").build_edge()
                .on_tool("t_alt").on_success("sA").build_edge()
                .build_state()

            # s1
            .define_state("s1")
                .on_tool("t_next").on_success("s2").build_edge()
                .on_tool("t_abort").on_error("sT", terminal=True).build_edge()
                .build_state()

            # sA branch merging into s2
            .define_state("sA")
                .on_tool("t_merge").on_success("s2").build_edge()
                .build_state()

            # s2 with cycle back to s1 and terminal to sT
            .define_state("s2")
                .on_tool("t_back").on_success("s1").build_edge()
                .on_tool("t_finish").on_success("sT", terminal=True).build_edge()
                .build_state()
    )




    # Build (validation happens here)
    app._build_state_machine()
    app._init_state_aware_managers()

    sm = app._state_machine
    assert sm is not None and sm.current_state(None) == "s0"
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
    assert sm is not None and sm.current_state(None) == "s0"

    async with sm.step(
        success_symbol=InputSymbol.for_tool("t_login", ToolResultType.SUCCESS),
        error_symbol=InputSymbol.for_tool("t_login", ToolResultType.ERROR),
    ):
        pass
    assert sm.current_state(None) == "s1"

    async with sm.step(
        success_symbol=InputSymbol.for_tool("t_next", ToolResultType.SUCCESS),
        error_symbol=InputSymbol.for_tool("t_next", ToolResultType.ERROR),
    ):
        pass
    assert sm.current_state(None) == "s2"

    async with sm.step(
        success_symbol=InputSymbol.for_tool("t_back", ToolResultType.SUCCESS),
        error_symbol=InputSymbol.for_tool("t_back", ToolResultType.ERROR),
    ):
        pass
    assert sm.current_state(None) == "s1"  # cycle back

    async with sm.step(
        success_symbol=InputSymbol.for_tool("t_next", ToolResultType.SUCCESS),
        error_symbol=InputSymbol.for_tool("t_next", ToolResultType.ERROR),
    ):
        pass
    assert sm.current_state(None) == "s2"

    async with sm.step(
        success_symbol=InputSymbol.for_tool("t_finish", ToolResultType.SUCCESS),
        error_symbol=InputSymbol.for_tool("t_finish", ToolResultType.ERROR),
    ):
        pass
    # sT is terminal → auto-reset
    assert sm.current_state(None) == "s0"


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
    assert sm is not None and sm.current_state(None) == "s0"

    async with sm.step(
        success_symbol=InputSymbol.for_tool("t_alt", ToolResultType.SUCCESS),
        error_symbol=InputSymbol.for_tool("t_alt", ToolResultType.ERROR),
    ):
        pass
    assert sm.current_state(None) == "sA"

    async with sm.step(
        success_symbol=InputSymbol.for_tool("t_merge", ToolResultType.SUCCESS),
        error_symbol=InputSymbol.for_tool("t_merge", ToolResultType.ERROR),
    ):
        pass
    assert sm.current_state(None) == "s2"

    async with sm.step(
        success_symbol=InputSymbol.for_tool("t_finish", ToolResultType.SUCCESS),
        error_symbol=InputSymbol.for_tool("t_finish", ToolResultType.ERROR),
    ):
        pass
    assert sm.current_state(None) == "s0"  # reset after terminal


@pytest.mark.anyio
async def test_path_C_abort_from_s1_to_terminal(app_branch_cycle_machine: StatefulMCP) -> None:
    """
    Path C:
      s0 --t_login/SUCCESS--> s1
      s1 --t_abort/ERROR----> sT (terminal) -> auto reset to s0
    """
    app = app_branch_cycle_machine
    sm = app._state_machine
    assert sm is not None and sm.current_state(None) == "s0"

    async with sm.step(
        success_symbol=InputSymbol.for_tool("t_login", ToolResultType.SUCCESS),
        error_symbol=InputSymbol.for_tool("t_login", ToolResultType.ERROR),
    ):
        pass
    assert sm.current_state(None) == "s1"

    with pytest.raises(ValueError):
        async with sm.step(
            success_symbol=InputSymbol.for_tool("t_abort", ToolResultType.SUCCESS),
            error_symbol=InputSymbol.for_tool("t_abort", ToolResultType.ERROR),
        ):
            raise ValueError()

    assert sm.current_state(None) == "s0"  # reset after terminal