# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedImport=false, reportUnusedVariable=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeArgument=false, reportUnknownParameterType=false

import pytest
from pytest import LogCaptureFixture

from mcp.server.state.builder import _InternalStateMachineBuilder
from mcp.server.state.machine.state_machine import InputSymbol
from mcp.server.state.server import StatefulMCP
from mcp.server.state.types import ToolResultType
from mcp.server.state.transaction.manager import TransactionManager


def test_builder_raises_on_second_initial_state():
    """
    Defining a second initial state should raise immediately in the builder,
    before validation is even invoked.
    """
    app = StatefulMCP(name="double_initial_buildtime")

    @app.tool()
    async def t_ok() -> str:
        return "ok"

    # First initial is fine
    sb = app.statebuilder
    sb.define_state("s0", is_initial=True).build_state()

    # Second initial should blow up at define-time (builder layer)
    with pytest.raises(ValueError) as ei:
        sb.define_state("s1", is_initial=True).build_state()

    assert "Initial state already set" in str(ei.value)


def test_builder_update_ignored_when_update_false(caplog: LogCaptureFixture):
    """
    add_or_update_state(): existing & update=False → config ignored, transitions preserved.
    Also verify debug log is emitted.
    """
    # Bare internal builder with empty managers (they are not used here)
    b = _InternalStateMachineBuilder(
        tool_manager=None, resource_manager=None, prompt_manager=None, tx_manager=TransactionManager())

    # Create initial state s0 (initial, non-terminal)
    b.add_or_update_state("s0", is_initial=True, is_terminal=False)

    # Try to flip it to terminal with update=False → should be ignored
    with caplog.at_level("DEBUG"):
        b.add_or_update_state("s0", is_terminal=True, update=False)

    # State remains non-terminal (ignored change)
    s0 = b._states["s0"]
    assert s0.is_terminal is False
    assert any("already exists; update=False" in rec.message for rec in caplog.records)


def test_builder_update_replaces_config_and_clears_transitions():
    """
    add_or_update_state(): existing & update=True → replace config and clear transitions.
    """
    b = _InternalStateMachineBuilder(
        tool_manager=None, resource_manager=None, prompt_manager=None, tx_manager=TransactionManager())

    # Create s0 + a transition s0 --(tool: t)-> s1
    b.add_or_update_state("s0", is_initial=True, is_terminal=False)
    b.add_or_update_state("s1", is_initial=False, is_terminal=False)

    sym = InputSymbol.for_tool("t", ToolResultType.SUCCESS)
    b.add_transition("s0", "s1", sym)

    assert len(b._states["s0"].transitions) == 1

    # Now replace s0 config with update=True → transitions must be cleared
    b.add_or_update_state("s0", is_initial=True, is_terminal=True, update=True)

    s0 = b._states["s0"]
    assert s0.is_initial is True
    assert s0.is_terminal is True
    assert s0.transitions == []  # cleared

def test_builder_duplicate_transition_warns_and_is_ignored(caplog: LogCaptureFixture):
    """
    add_transition(): adding the same transition twice should warn and ignore the duplicate.
    """
    b = _InternalStateMachineBuilder(
        tool_manager=None, resource_manager=None, prompt_manager=None, tx_manager=TransactionManager())
    b.add_or_update_state("s0")
    b.add_or_update_state("s1")

    sym = InputSymbol.for_tool("t", ToolResultType.SUCCESS)

    with caplog.at_level("WARNING"):
        b.add_transition("s0", "s1", sym)
        b.add_transition("s0", "s1", sym)  # duplicate

    s0 = b._states["s0"]
    assert len(s0.transitions) == 1
    assert any("already exists; new definition ignored" in rec.message for rec in caplog.records)


def test_builder_ambiguous_transition_warns_and_is_ignored(caplog: LogCaptureFixture):
    """
    add_transition(): same symbol to a different target should warn about ambiguity and ignore the new one.
    """
    b = _InternalStateMachineBuilder(
        tool_manager=None, resource_manager=None, prompt_manager=None, tx_manager=TransactionManager())
    b.add_or_update_state("s0")
    b.add_or_update_state("s1")
    b.add_or_update_state("s2")

    sym = InputSymbol.for_tool("t", ToolResultType.SUCCESS)

    with caplog.at_level("WARNING"):
        b.add_transition("s0", "s1", sym)
        b.add_transition("s0", "s2", sym)  # ambiguous

    s0 = b._states["s0"]
    assert len(s0.transitions) == 1
    assert s0.transitions[0].to_state == "s1"
    assert any("Ambiguous transition" in rec.message for rec in caplog.records)
