# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedImport=false, reportUnusedVariable=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeArgument=false, reportUnknownParameterType=false

import pytest
from pytest import LogCaptureFixture

from mcp.server.state.server import StatefulMCP
from mcp.server.state.types import ToolResultType, PromptResultType, ResourceResultType

def test_validation_error_no_initial_state():
    """No state is marked as initial → validator must fail on build."""
    app = StatefulMCP(name="no_initial")

    @app.tool()
    async def t_ok() -> str:
        return "ok"

    (
        app.statebuilder
            .define_state("s0")
            .transition("s1").on_tool("t_ok", result=ToolResultType.SUCCESS).done()
            .define_state("s1")
            .done()
    )

    with pytest.raises(ValueError) as ei:
        app._build_state_machine_once()

    assert "No initial state defined." in str(ei.value)


def test_validation_error_terminal_has_outgoing():
    """Terminal states must not define outgoing transitions → validator fails on build."""
    app = StatefulMCP(name="terminal_outgoing")

    @app.tool()
    async def t_ok() -> str:
        return "ok"

    (
        app.statebuilder
            .define_state("s0", is_initial=True)
            .transition("s1").on_tool("t_ok", result=ToolResultType.SUCCESS).done()
            .define_state("s1", is_terminal=True)
            .transition("s0").on_tool("t_ok", result=ToolResultType.SUCCESS).done()  # illegal outgoing
    )

    with pytest.raises(ValueError) as ei:
        app._build_state_machine_once()

    assert "Terminal state 's1' must not have outgoing transitions." in str(ei.value)


def test_validation_error_no_reachable_terminal():
    """
    No reachable terminal state from the initial → validator fails on build.
    We ensure s1 is explicitly non-terminal to avoid any implicit terminal behavior.
    """
    app = StatefulMCP(name="no_reachable_terminal")
    
    (
        app.statebuilder
            .define_state("s0", is_initial=True)
            .transition("s1").on_tool("t_ok", result=ToolResultType.SUCCESS).done()
            .define_state("s1") # define updated isTermianl to False
    )

    with pytest.raises(ValueError) as ei:
        app._build_state_machine_once()

    assert "No reachable terminal state from initial." in str(ei.value)


def test_validation_error_no_reachable_terminal_no_valid_edge():
    """
    No reachable terminal state from the initial → validator fails on build.
    We ensure the necessary tool for the required edge to terminal does not exists.
    """
    app = StatefulMCP(name="no_reachable_terminal")
    
    (
        app.statebuilder
            .define_state("s0", is_initial=True)
            .transition("s1").on_tool("t_ok", result=ToolResultType.SUCCESS).done()
            .define_state("s1")
            .transition("sT").on_tool("t_ok", result=ToolResultType.SUCCESS).done()
    )

    with pytest.raises(ValueError) as ei:
        app._build_state_machine_once()

    assert "No reachable terminal state from initial." in str(ei.value)


def test_validation_error_missing_tool():
    """Referenced tool does not exist → validator fails on build."""
    app = StatefulMCP(name="missing_tool")

    (
        app.statebuilder
            .define_state("s0", is_initial=True)
            .transition("s1").on_tool("MISSING", result=ToolResultType.SUCCESS).done()
            .define_state("s1", is_terminal=True)
            .done()
    )

    with pytest.raises(ValueError) as ei:
        app._build_state_machine_once()

    assert "Referenced tool 'MISSING' is not registered." in str(ei.value)


def test_validation_error_missing_prompt():
    """Referenced prompt does not exist → validator fails on build."""
    app = StatefulMCP(name="missing_prompt")

    (
        app.statebuilder
            .define_state("s0", is_initial=True)
            .transition("s1").on_prompt("MISSING", result=PromptResultType.SUCCESS).done()
            .define_state("s1", is_terminal=True)
            .done()
    )

    with pytest.raises(ValueError) as ei:
        app._build_state_machine_once()

    assert "Referenced prompt 'MISSING' is not registered." in str(ei.value)


def test_validation_error_missing_resource():
    """Referenced resource does not exist → validator fails on build."""
    app = StatefulMCP(name="missing_resource")

    (
        app.statebuilder
            .define_state("s0", is_initial=True)
            .transition("s1").on_resource("resource://missing", result=ResourceResultType.SUCCESS).done()
            .define_state("s1", is_terminal=True)
            .done()
    )

    with pytest.raises(ValueError) as ei:
        app._build_state_machine_once()

    assert "Referenced resource 'resource://missing' is not registered." in str(ei.value)


def test_validation_warning_unreachable_state(caplog: LogCaptureFixture):
    """
    Unreachable state should be logged as a WARNING but must not fail the build.
    """
    app = StatefulMCP(name="unreachable_state")

    @app.tool()
    async def t_ok() -> str:
        return "ok"

    (
        app.statebuilder
            .define_state("s0", is_initial=True)
            .transition("s1").on_tool("t_ok", result=ToolResultType.SUCCESS).done()
            .define_state("s1", is_terminal=True)
            .done()
            .define_state("sX")  # unreachable
            .done()
    )

    with caplog.at_level("WARNING"):
        app._build_state_machine_once()

    assert any("State 'sX' is unreachable from initial." in rec.message for rec in caplog.records), \
        "Expected unreachable-state warning was not logged."
