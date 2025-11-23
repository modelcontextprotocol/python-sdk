# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedImport=false, reportUnusedVariable=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeArgument=false, reportUnknownParameterType=false, reportMissingTypeStubs=false

import pytest
from pytest import LogCaptureFixture

from mcp.server.state.server import StatefulMCP


def test_validation_error_no_initial_state() -> None:
    """No state is marked as initial → validator must fail on build."""
    app = StatefulMCP(name="no_initial")

    @app.tool()
    async def t_ok() -> str:
        return "ok"

    (
        app.statebuilder
            .define_state("s0")
            .on_tool("t_ok").on_success("s1").build_edge().build_state()
            .define_state("s1").build_state()
    )

    with pytest.raises(ValueError) as ei:
        app._build_state_machine()

    assert "No initial state defined." in str(ei.value)


def test_validation_warns_and_prunes_unreachable_edges(caplog: LogCaptureFixture) -> None:
    """
    If a state's ONLY incoming edge is terminal, its outgoings are unreachable.
    Validator should WARN and prune those outgoings (no exception).
    """
    app = StatefulMCP(name="terminal_outgoing")

    @app.tool()
    async def t_ok() -> str:
        return "ok"

    (
        app.statebuilder
            .define_state("s0", is_initial=True)
            # s0 --(t_ok/SUCCESS, terminal)--> s1  ⇒ entering s1 always terminates
            .on_tool("t_ok").on_success("s1", terminal=True).build_edge().build_state()
            # s1 defines an outgoing edge, but it is unreachable and should be pruned
            .define_state("s1")
            .on_tool("t_ok").on_success("s0").build_edge().build_state()
    )

    with caplog.at_level("WARNING"):
        app._build_state_machine()

    # Warning logged about pruning outgoings for s1 (wording changed in new validator)
    assert any(
        ("validation warning:" in rec.message.lower())
        and ("pruned" in rec.message.lower())
        and ("'s1'" in rec.message.lower())
        for rec in caplog.records
    ), "Expected pruning warning for state 's1'"

    # Outgoings of s1 were pruned. States no longer carry deltas; assert via runtime API.
    assert app._state_machine is not None
    m = app._state_machine
    m.set_current_state("s1")
    assert m.available_symbols("tool") == set()


def test_validation_error_no_reachable_terminal() -> None:
    """
    No reachable terminal state from the initial → validator fails on build.
    """
    app = StatefulMCP(name="no_reachable_terminal")

    @app.tool()
    async def t_ok() -> str:
        return "ok"

    (
        app.statebuilder
            .define_state("s0", is_initial=True)
            .on_tool("t_ok").on_success("s1").build_edge().build_state()
            .define_state("s1").build_state()
    )

    with pytest.raises(ValueError) as ei:
        app._build_state_machine()

    assert "No reachable terminal state from initial." in str(ei.value)


def test_validation_error_no_reachable_terminal_no_valid_edge() -> None:
    """
    If the only path to a terminal would require a missing artifact, build should fail.
    We assert the missing-artifact error (which is strictly invalid) rather than terminal reachability.
    """
    app = StatefulMCP(name="no_reachable_terminal_missing")

    # No registration of 't_ok' on purpose
    (
        app.statebuilder
            .define_state("s0", is_initial=True)
            .on_tool("t_ok").on_success("s1").build_edge().build_state()
            .define_state("s1")
            # terminal edge depends on missing tool 't_ok'
            .on_tool("t_ok").on_success("sT", terminal=True).build_edge().build_state()
    )

    with pytest.raises(ValueError) as ei:
        app._build_state_machine()

    # Primary failure: missing tool reference
    assert "Referenced tool 't_ok' is not registered." in str(ei.value)


def test_validation_error_missing_tool() -> None:
    """Referenced tool does not exist → validator fails on build."""
    app = StatefulMCP(name="missing_tool")

    (
        app.statebuilder
            .define_state("s0", is_initial=True)
            .on_tool("MISSING").on_success("s1").build_edge()
    )

    with pytest.raises(ValueError) as ei:
        app._build_state_machine()

    assert "Referenced tool 'MISSING' is not registered." in str(ei.value)


def test_validation_error_missing_prompt() -> None:
    """Referenced prompt does not exist → validator fails on build."""
    app = StatefulMCP(name="missing_prompt")

    (
        app.statebuilder
            .define_state("s0", is_initial=True)
            .on_prompt("MISSING").on_success("s1").build_edge()
    )

    with pytest.raises(ValueError) as ei:
        app._build_state_machine()

    assert "Referenced prompt 'MISSING' is not registered." in str(ei.value)


def test_validation_error_missing_resource() -> None:
    """Referenced resource does not exist → validator fails on build."""
    app = StatefulMCP(name="missing_resource")

    (
        app.statebuilder
            .define_state("s0", is_initial=True)
            .on_resource("resource://missing").on_success("s1").build_edge()
    )

    with pytest.raises(ValueError) as ei:
        app._build_state_machine()

    assert "Referenced resource 'resource://missing' is not registered." in str(ei.value)


def test_validation_warning_unreachable_state(caplog: LogCaptureFixture) -> None:
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
            # Make s1 reachable and terminal via incoming terminal edge
            .on_tool("t_ok").on_success("s1", terminal=True).build_edge().build_state()
            .define_state("s1").build_state()
            # sX stays unreachable
            .define_state("sX").build_state()
    )

    with caplog.at_level("WARNING"):
        app._build_state_machine()

    assert any(
        "State machine validation warning: State 'sX' is unreachable from initial and was removed." in rec.message
        for rec in caplog.records
    ), "Expected unreachable-state warning was not logged."
