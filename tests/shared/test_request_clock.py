"""`request_clock` cases the end-to-end tests in `tests/interaction/auth/test_login_time.py` cannot produce."""

from contextlib import ExitStack

import anyio
import pytest
from trio.testing import MockClock

from mcp.shared._request_clock import request_clock, waiting_on_a_person

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _module_runner_lease() -> None:
    """Opt out of the shared per-module event loop: this module parametrizes `anyio_backend`."""


# trio's autojumping virtual clock: the sleeps cost no real time and the measured seconds are exact.
@pytest.mark.parametrize(
    "anyio_backend",
    [pytest.param(("trio", {"clock": MockClock(autojump_threshold=0)}), id="trio-mockclock")],
)
async def test_a_wait_that_began_before_the_clock_started_leaves_the_whole_budget() -> None:
    """A transport may reach the person before `send_raw_request` gets to start the clock (its write
    can hand the message over and only then yield), so starting must not resume a clock that is paused."""
    began = anyio.current_time()

    with anyio.fail_after(1000), pytest.raises(TimeoutError):  # virtual seconds, so the guard has to outlast the waits
        with request_clock(10) as clock:
            with waiting_on_a_person():
                await anyio.sleep(60)
                clock.start()
                await anyio.sleep(60)
            await anyio.sleep_forever()

    assert anyio.current_time() - began == 60 + 60 + 10


async def test_the_clock_stops_and_resumes_on_asyncio() -> None:
    """The end-to-end tests need trio's virtual clock; this is the same stop and resume on the backend users run."""
    outlasted_the_budget = False

    with anyio.fail_after(5), pytest.raises(TimeoutError):
        with request_clock(0.01) as clock:
            clock.start()
            with waiting_on_a_person():
                await anyio.sleep(0.05)  # real time, under test: five budgets go by while the clock is stopped
            outlasted_the_budget = True
            await anyio.sleep_forever()

    assert outlasted_the_budget


async def test_a_wait_that_begins_after_the_budget_ran_out_does_not_swallow_the_timeout() -> None:
    """The deadline fires, and before the waiting task wakes up the transport's task reaches the person.

    asyncio only: there, starting a clock with nothing left cancels the scope on the spot, which puts
    the two events in that order without a race. The wait outlives the request, as a login does.
    """
    with anyio.fail_after(5), ExitStack() as login, pytest.raises(TimeoutError):
        with request_clock(0) as clock:
            clock.start()
            login.enter_context(waiting_on_a_person())
            await anyio.sleep_forever()
