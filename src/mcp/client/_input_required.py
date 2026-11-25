"""SEP-2322 client-side multi-round-trip driver.

When a server returns `InputRequiredResult` instead of the normal result of a
`tools/call` / `prompts/get` / `resources/read`, the client fulfils the
embedded `input_requests` (sampling, elicitation, roots) and retries the
original request carrying the responses and the echoed opaque `request_state`.
This module implements that retry loop as a pure function so it can drive any
of the three methods identically; `Client` builds the `dispatch` and `retry`
closures, `ClientSession` stays mechanics-only.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

import anyio
import anyio.abc
from mcp_types import ErrorData, InputRequest, InputRequiredResult, InputResponse, InputResponses

from mcp.shared.exceptions import MCPError

DEFAULT_INPUT_REQUIRED_MAX_ROUNDS = 10
"""Default cap on `InputRequiredResult` retry rounds before the driver gives up.

Matches the typescript-sdk default; csharp-sdk and go-sdk use the same value
as a hard constant.
"""

_STATE_ONLY_BACKOFF_INITIAL_SECONDS = 0.05
"""First sleep when an `InputRequiredResult` carries only `request_state` (no input requests)."""

_STATE_ONLY_BACKOFF_CAP_SECONDS = 0.25
"""Upper bound on the state-only backoff sleep; reached after three consecutive state-only legs."""


ResultT = TypeVar("ResultT")


class InputRequiredRoundsExceededError(RuntimeError):
    """The server kept returning `InputRequiredResult` past the configured `max_rounds`."""

    def __init__(self, max_rounds: int) -> None:
        super().__init__(
            f"Server returned InputRequiredResult for more than {max_rounds} rounds; "
            "raise input_required_max_rounds on the Client, or use "
            "client.session.<method>(..., allow_input_required=True) to drive the loop manually."
        )
        self.max_rounds = max_rounds


async def run_input_required_driver(
    first: InputRequiredResult,
    *,
    dispatch: Callable[[str, InputRequest], Awaitable[InputResponse | ErrorData]],
    retry: Callable[[InputResponses | None, str | None], Awaitable[ResultT | InputRequiredResult]],
    max_rounds: int = DEFAULT_INPUT_REQUIRED_MAX_ROUNDS,
) -> ResultT:
    """Resolve an `InputRequiredResult` to its terminal result.

    Loops until `retry` returns a non-`InputRequiredResult`, or `max_rounds` is
    exhausted. Each round either dispatches all `input_requests` concurrently
    and retries with the collected responses, or — when the server sent only
    `request_state` — sleeps with exponential backoff (50ms doubling to a 250ms
    cap, reset by any leg that carries input requests) and retries empty.
    `request_state` is passed through byte-exact and never inspected.

    Args:
        first: The `InputRequiredResult` the original call returned.
        dispatch: Runs one embedded `InputRequest` through the client's
            sampling / elicitation / roots callbacks. Called concurrently per
            request key. An `ErrorData` return aborts the loop as an `MCPError`.
        retry: Re-issues the original request with the collected responses and
            the latest `request_state`. Each call mints a fresh JSON-RPC id.
        max_rounds: Cap on retry rounds.

    Raises:
        InputRequiredRoundsExceededError: `max_rounds` exhausted.
        MCPError: A `dispatch` call returned `ErrorData`.
    """
    rounds = 0
    state_only_delay = _STATE_ONLY_BACKOFF_INITIAL_SECONDS
    current: ResultT | InputRequiredResult = first
    while isinstance(current, InputRequiredResult):
        rounds += 1
        if rounds > max_rounds:
            raise InputRequiredRoundsExceededError(max_rounds)
        if current.input_requests:
            state_only_delay = _STATE_ONLY_BACKOFF_INITIAL_SECONDS
            responses: InputResponses | None = await _dispatch_all(current.input_requests, dispatch)
        else:
            await anyio.sleep(state_only_delay)
            state_only_delay = min(state_only_delay * 2, _STATE_ONLY_BACKOFF_CAP_SECONDS)
            responses = None
        current = await retry(responses, current.request_state)
    return current


async def _dispatch_all(
    requests: dict[str, InputRequest],
    dispatch: Callable[[str, InputRequest], Awaitable[InputResponse | ErrorData]],
) -> InputResponses:
    """Run `dispatch` concurrently for every key, raising `MCPError` on the first `ErrorData`.

    The first task to return `ErrorData` cancels its siblings via the task
    group's cancel scope, so a refused input does not wait on a slow peer.
    A callback that *raises* propagates as an `ExceptionGroup` like any other
    task-group failure.
    """
    responses: InputResponses = {}
    refused: ErrorData | None = None

    async def run_one(tg: anyio.abc.TaskGroup, key: str, req: InputRequest) -> None:
        nonlocal refused
        result = await dispatch(key, req)
        if isinstance(result, ErrorData):
            refused = result
            tg.cancel_scope.cancel()
        else:
            responses[key] = result

    async with anyio.create_task_group() as tg:
        for key, req in requests.items():
            tg.start_soon(run_one, tg, key, req)
    if refused is not None:
        raise MCPError.from_error_data(refused)
    return responses
