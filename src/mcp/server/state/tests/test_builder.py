# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedImport=false, reportUnusedVariable=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeArgument=false, reportUnknownParameterType=false

import pytest
from pytest import LogCaptureFixture

from mcp.server.state.builder import _InternalStateMachineBuilder
from mcp.server.state.machine.state_machine import InputSymbol
from mcp.server.state.types import ToolResultType
from mcp.server.state.transaction.manager import TransactionManager


def test_builder_warns_on_second_initial_state(caplog: LogCaptureFixture) -> None:
    """
    Defining a second initial state does NOT raise; it logs a WARNING and keeps
    the first initial unchanged.
    """
    b = _InternalStateMachineBuilder(
        tool_manager=None, resource_manager=None, prompt_manager=None, tx_manager=TransactionManager()
    )

    # First initial is accepted
    b.add_state("s0", is_initial=True)

    # Second initial → warning, ignored
    with caplog.at_level("WARNING"):
        b.add_state("s1", is_initial=True)

    assert b._initial == "s0"
    assert any("Initial state already set" in rec.message for rec in caplog.records)


def test_define_state_does_not_clear_edges(caplog: LogCaptureFixture) -> None:
    """
    Calling add_state() again for an existing state does not replace config or clear edges.
    A DEBUG log should mention that the definition is ignored.
    """
    b = _InternalStateMachineBuilder(
        tool_manager=None, resource_manager=None, prompt_manager=None, tx_manager=TransactionManager()
    )

    b.add_state("s0", is_initial=True)
    b.add_state("s1")

    sym = InputSymbol.for_tool("t", ToolResultType.SUCCESS)
    b.add_edge("s0", "s1", sym)

    assert len(b._states["s0"].deltas) == 1  # one edge exists

    # Re-define same state → ignored, edges stay intact
    with caplog.at_level("DEBUG"):
        b.add_state("s0", is_initial=True)

    assert len(b._states["s0"].deltas) == 1
    assert any("State 's0' already exists; keeping configuration." in rec.message for rec in caplog.records)


def test_add_terminal_marks_target_state() -> None:
    """
    add_terminal(to_state, symbol) marks that state's terminal symbol set.
    """
    b = _InternalStateMachineBuilder(
        tool_manager=None, resource_manager=None, prompt_manager=None, tx_manager=TransactionManager()
    )
    b.add_state("s0", is_initial=True)
    b.add_state("s1")

    sym = InputSymbol.for_tool("login", ToolResultType.SUCCESS)
    b.add_edge("s0", "s1", sym)
    b.add_terminal("s1", sym)

    assert sym in b._states["s1"].terminals


def test_builder_duplicate_edge_warns_and_is_ignored(caplog: LogCaptureFixture) -> None:
    """
    add_edge(): adding the exact same edge twice should warn and ignore the duplicate.
    """
    b = _InternalStateMachineBuilder(
        tool_manager=None, resource_manager=None, prompt_manager=None, tx_manager=TransactionManager()
    )
    b.add_state("s0")
    b.add_state("s1")

    sym = InputSymbol.for_tool("t", ToolResultType.SUCCESS)

    with caplog.at_level("WARNING"):
        b.add_edge("s0", "s1", sym)
        b.add_edge("s0", "s1", sym)  # duplicate

    s0 = b._states["s0"]
    assert len(s0.deltas) == 1
    assert any("already exists" in rec.message and "ignored" in rec.message for rec in caplog.records)


def test_builder_ambiguous_edge_warns_and_is_ignored(caplog: LogCaptureFixture) -> None:
    """
    add_edge(): mapping the same symbol to a different target from the same source
    should warn about ambiguity and ignore the new edge.
    """
    b = _InternalStateMachineBuilder(
        tool_manager=None, resource_manager=None, prompt_manager=None, tx_manager=TransactionManager()
    )
    b.add_state("s0")
    b.add_state("s1")
    b.add_state("s2")

    sym = InputSymbol.for_tool("t", ToolResultType.SUCCESS)

    with caplog.at_level("WARNING"):
        b.add_edge("s0", "s1", sym)
        b.add_edge("s0", "s2", sym)  # ambiguous

    s0 = b._states["s0"]
    assert len(s0.deltas) == 1
    assert s0.deltas[0].to_state == "s1"
    assert any("Ambiguous edge" in rec.message for rec in caplog.records)
