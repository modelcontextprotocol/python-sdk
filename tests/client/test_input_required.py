"""Unit tests for the SEP-2322 client-side multi-round-trip driver.

`run_input_required_driver` is pure, so these tests hand-build its `dispatch`/`retry`
closures and never touch a `ClientSession`; integration lives in `test_client.py`.
"""

import anyio
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INVALID_REQUEST,
    CallToolResult,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    ErrorData,
    InputRequest,
    InputRequiredResult,
    InputResponse,
    InputResponses,
    TextContent,
)
from trio.testing import MockClock

from mcp import MCPError
from mcp.client._input_required import (
    _STATE_ONLY_BACKOFF_CAP_SECONDS,
    _STATE_ONLY_BACKOFF_INITIAL_SECONDS,
    DEFAULT_INPUT_REQUIRED_MAX_ROUNDS,
    InputRequiredRoundsExceededError,
    run_input_required_driver,
)

pytestmark = pytest.mark.anyio


def _elicit(message: str = "What is your name?") -> ElicitRequest:
    schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
    return ElicitRequest(params=ElicitRequestFormParams(message=message, requested_schema=schema))


async def _never_dispatch(key: str, req: InputRequest) -> InputResponse | ErrorData:
    """Dispatch closure for tests whose script never carries `input_requests`."""
    raise NotImplementedError


async def test_single_round_dispatches_then_retries_to_terminal_result() -> None:
    first = InputRequiredResult(input_requests={"ask": _elicit()})
    terminal = CallToolResult(content=[TextContent(text="done")])
    dispatched: list[tuple[str, InputRequest]] = []
    retried: list[tuple[InputResponses | None, str | None]] = []

    async def dispatch(key: str, req: InputRequest) -> InputResponse | ErrorData:
        dispatched.append((key, req))
        return ElicitResult(action="accept", content={"name": "Ada"})

    async def retry(responses: InputResponses | None, state: str | None) -> CallToolResult | InputRequiredResult:
        retried.append((responses, state))
        return terminal

    with anyio.fail_after(5):
        result = await run_input_required_driver(first, dispatch=dispatch, retry=retry, max_rounds=3)

    assert result is terminal
    assert first.input_requests is not None
    assert dispatched == [("ask", first.input_requests["ask"])]
    assert retried == [({"ask": ElicitResult(action="accept", content={"name": "Ada"})}, None)]


async def test_multi_round_loops_until_retry_returns_non_input_required() -> None:
    terminal = CallToolResult(content=[TextContent(text="done")])
    script: list[CallToolResult | InputRequiredResult] = [
        InputRequiredResult(input_requests={"b": _elicit("second?")}),
        terminal,
    ]
    retried: list[tuple[InputResponses | None, str | None]] = []
    dispatched_keys: list[str] = []

    async def dispatch(key: str, req: InputRequest) -> InputResponse | ErrorData:
        dispatched_keys.append(key)
        return ElicitResult(action="decline")

    async def retry(responses: InputResponses | None, state: str | None) -> CallToolResult | InputRequiredResult:
        retried.append((responses, state))
        return script.pop(0)

    first = InputRequiredResult(input_requests={"a": _elicit("first?")})
    with anyio.fail_after(5):
        result = await run_input_required_driver(first, dispatch=dispatch, retry=retry, max_rounds=5)

    assert result is terminal
    assert dispatched_keys == ["a", "b"]
    assert retried == snapshot(
        [
            ({"a": ElicitResult(action="decline")}, None),
            ({"b": ElicitResult(action="decline")}, None),
        ]
    )


async def test_exceeding_max_rounds_raises_with_the_configured_cap() -> None:
    rounds: list[int] = []

    async def dispatch(key: str, req: InputRequest) -> InputResponse | ErrorData:
        return ElicitResult(action="decline")

    async def retry(responses: InputResponses | None, state: str | None) -> CallToolResult | InputRequiredResult:
        rounds.append(len(rounds))
        return InputRequiredResult(input_requests={"again": _elicit()})

    first = InputRequiredResult(input_requests={"again": _elicit()})
    with anyio.fail_after(5):
        with pytest.raises(InputRequiredRoundsExceededError) as exc:
            await run_input_required_driver(first, dispatch=dispatch, retry=retry, max_rounds=3)

    assert exc.value.max_rounds == 3
    # `first` counts as round 1; rounds 1-3 each retry, round 4 trips the cap before dispatching.
    assert len(rounds) == 3


async def test_dispatch_returning_error_data_aborts_the_loop_as_mcp_error() -> None:
    async def dispatch(key: str, req: InputRequest) -> InputResponse | ErrorData:
        return ErrorData(code=INVALID_REQUEST, message="not supported")

    async def retry(responses: InputResponses | None, state: str | None) -> CallToolResult | InputRequiredResult:
        raise NotImplementedError  # unreachable: dispatch errored before any retry

    first = InputRequiredResult(input_requests={"ask": _elicit()})
    with anyio.fail_after(5):
        with pytest.raises(MCPError) as exc:
            await run_input_required_driver(first, dispatch=dispatch, retry=retry, max_rounds=3)
    assert exc.value.error.code == INVALID_REQUEST


async def test_request_state_passes_through_byte_identical() -> None:
    states = ['{"round": 1, "tag": "héllo"}', '{"round": 2, "tag": "wörld"}']
    received_states: list[str | None] = []

    async def dispatch(key: str, req: InputRequest) -> InputResponse | ErrorData:
        return ElicitResult(action="decline")

    async def retry(responses: InputResponses | None, state: str | None) -> CallToolResult | InputRequiredResult:
        received_states.append(state)
        if len(received_states) < 2:
            return InputRequiredResult(input_requests={"k": _elicit()}, request_state=states[1])
        return CallToolResult(content=[])

    first = InputRequiredResult(input_requests={"k": _elicit()}, request_state=states[0])
    with anyio.fail_after(5):
        await run_input_required_driver(first, dispatch=dispatch, retry=retry, max_rounds=3)

    assert received_states[0] is states[0]
    assert received_states[1] is states[1]


# Trio's autojumping MockClock makes the backoff sleeps instant and the recorded deltas exact.
@pytest.mark.parametrize(
    "anyio_backend",
    [pytest.param(("trio", {"clock": MockClock(autojump_threshold=0)}), id="trio-mockclock")],
)
async def test_state_only_legs_back_off_exponentially_to_the_cap() -> None:
    retry_times: list[float] = []

    async def retry(responses: InputResponses | None, state: str | None) -> CallToolResult | InputRequiredResult:
        retry_times.append(anyio.current_time())
        assert responses is None
        if len(retry_times) == 6:
            return CallToolResult(content=[])
        return InputRequiredResult(request_state="poll")

    start = anyio.current_time()
    first = InputRequiredResult(request_state="poll")
    await run_input_required_driver(first, dispatch=_never_dispatch, retry=retry, max_rounds=10)

    deltas = [round(retry_times[0] - start, 9)] + [
        round(retry_times[i] - retry_times[i - 1], 9) for i in range(1, len(retry_times))
    ]
    assert deltas == snapshot([0.05, 0.1, 0.2, 0.25, 0.25, 0.25])
    assert _STATE_ONLY_BACKOFF_INITIAL_SECONDS == 0.05
    assert _STATE_ONLY_BACKOFF_CAP_SECONDS == 0.25


@pytest.mark.parametrize(
    "anyio_backend",
    [pytest.param(("trio", {"clock": MockClock(autojump_threshold=0)}), id="trio-mockclock")],
)
async def test_backoff_counter_resets_after_a_leg_with_input_requests() -> None:
    script: list[CallToolResult | InputRequiredResult] = [
        InputRequiredResult(request_state="s"),
        InputRequiredResult(input_requests={"k": _elicit()}),
        InputRequiredResult(request_state="s"),
        CallToolResult(content=[]),
    ]
    retry_times: list[float] = []

    async def dispatch(key: str, req: InputRequest) -> InputResponse | ErrorData:
        return ElicitResult(action="decline")

    async def retry(responses: InputResponses | None, state: str | None) -> CallToolResult | InputRequiredResult:
        retry_times.append(anyio.current_time())
        return script.pop(0)

    start = anyio.current_time()
    first = InputRequiredResult(request_state="s")
    await run_input_required_driver(first, dispatch=dispatch, retry=retry, max_rounds=10)

    deltas = [round(retry_times[0] - start, 9)] + [
        round(retry_times[i] - retry_times[i - 1], 9) for i in range(1, len(retry_times))
    ]
    # 0.05, 0.1 (two state-only), 0.0 (dispatch leg has no sleep), 0.05 (reset).
    assert deltas == snapshot([0.05, 0.1, 0.0, 0.05])


async def test_input_requests_are_dispatched_concurrently() -> None:
    keys = ["a", "b", "c"]
    started: set[str] = set()
    all_started = anyio.Event()

    async def dispatch(key: str, req: InputRequest) -> InputResponse | ErrorData:
        started.add(key)
        if started == set(keys):
            all_started.set()
        await all_started.wait()  # gate opens only when every key has started; sequential dispatch deadlocks here
        return ElicitResult(action="accept", content={"name": key})

    received: list[InputResponses | None] = []

    async def retry(responses: InputResponses | None, state: str | None) -> CallToolResult | InputRequiredResult:
        received.append(responses)
        return CallToolResult(content=[])

    first = InputRequiredResult(input_requests={k: _elicit() for k in keys})
    with anyio.fail_after(5):
        await run_input_required_driver(first, dispatch=dispatch, retry=retry, max_rounds=2)

    assert received[0] is not None
    assert received[0] == {k: ElicitResult(action="accept", content={"name": k}) for k in keys}


def test_default_max_rounds_constant() -> None:
    """SDK-defined default; matches the typescript-sdk."""
    assert DEFAULT_INPUT_REQUIRED_MAX_ROUNDS == 10
