"""Request timeouts around an interactive OAuth login: they measure the server, not the person.

A 401 makes `OAuthClientProvider` await the developer's `redirect_handler` and `callback_handler`
inside the challenged HTTP request, so the person's time in the browser passes while that
request's timeout is pending.

Every test runs on trio's autojumping virtual clock: time advances only when every task is
blocked, and then straight to the next deadline. In-process work therefore costs zero seconds, an
hour-long login costs no real wait, and the recorded times are exact. The `fail_after` guards
count virtual seconds too, so the ones around a login have to outlast it.

The tests that reach the handshake era ask the server for JSON responses: there the client stops
reading an SSE response at the answer, which leaves httpx2's generators to the garbage collector,
and trio (unlike asyncio) reports that as a `ResourceWarning`.
"""

import json
import math
from collections.abc import Callable

import anyio
import httpx2
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import REQUEST_TIMEOUT, ErrorData, ListToolsResult, Tool
from mcp_types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION
from starlette.types import ASGIApp, Receive, Scope, Send
from trio.testing import MockClock

from mcp import MCPError
from mcp.client.session import DISCOVER_TIMEOUT_SECONDS
from mcp.server import Server, ServerRequestContext
from mcp.shared.auth import AuthorizationCodeResult
from tests.interaction._requirements import requirement
from tests.interaction.auth._harness import AppShim, HeadlessOAuth, connect_with_oauth
from tests.interaction.auth._provider import InMemoryAuthorizationServerProvider

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.parametrize(
        "anyio_backend",
        [pytest.param(("trio", {"clock": MockClock(autojump_threshold=0)}), id="trio-mockclock")],
    ),
]

LOGIN_SECONDS = DISCOVER_TIMEOUT_SECONDS * 360


@pytest.fixture(autouse=True)
def _module_runner_lease() -> None:
    """Opt out of the shared per-module event loop: this module parametrizes `anyio_backend`."""


class Person(HeadlessOAuth):
    """Completes the authorize step like `HeadlessOAuth`, but takes `seconds` over it, half in each handler."""

    def __init__(self, seconds: float) -> None:
        super().__init__()
        self._seconds = seconds
        self.in_the_browser = anyio.Event()
        self.abandoned = anyio.Event()

    async def _take_half_the_time(self) -> None:
        try:
            await anyio.sleep(self._seconds / 2)  # virtual time: the clock jumps, nothing really waits
        except anyio.get_cancelled_exc_class():
            self.abandoned.set()
            raise

    async def redirect_handler(self, authorization_url: str) -> None:
        self.in_the_browser.set()
        await self._take_half_the_time()
        await super().redirect_handler(authorization_url)

    async def callback_handler(self) -> AuthorizationCodeResult:
        await self._take_half_the_time()
        return await super().callback_handler()


async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[Tool(name="echo", input_schema={"type": "object"})])


Timeline = list[tuple[float, str, bool]]


def record_timeline() -> tuple[Timeline, Callable[[httpx2.Request], None]]:
    """Build an `on_request` that logs each MCP POST as (virtual seconds since now, method, carries a token)."""
    timeline: Timeline = []
    start = anyio.current_time()

    def on_request(request: httpx2.Request) -> None:
        if request.method == "POST" and request.url.path == "/mcp":
            seconds = round(anyio.current_time() - start, 9)
            timeline.append((seconds, json.loads(request.content)["method"], "authorization" in request.headers))

    return timeline, on_request


def slow_then_silent_probe(*, challenge_after: float = 0.0) -> AppShim:
    """Build an `app_shim` whose server takes its time over `server/discover` and answers everything else.

    A probe without a token reaches the real app (and its 401) only after `challenge_after` seconds.
    A probe that would be served, because it carries a token or the endpoint is not gated, gets an
    SSE response that is opened and then never carries an event (the provider holds its lock until
    a request's response headers arrive, so with none the fallback `initialize` could not be sent).
    No real `Server` stalls on the probe, so the shim plays that part.
    """

    def factory(app: ASGIApp) -> ASGIApp:
        async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
            headers = dict(scope["headers"])
            if headers.get(b"mcp-method") == b"server/discover":
                if challenge_after and b"authorization" not in headers:
                    await anyio.sleep(challenge_after)
                else:
                    content_type = [(b"content-type", b"text/event-stream")]
                    await send({"type": "http.response.start", "status": 200, "headers": content_type})
                    await anyio.sleep_forever()
            await app(scope, receive, send)

        return wrapped

    return factory


def slow(path: str, seconds: float) -> AppShim:
    """Build an `app_shim` whose server takes `seconds` (`math.inf`: forever) to start on any request for `path`."""

    def factory(app: ASGIApp) -> ASGIApp:
        async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
            if scope["path"] == path:
                await anyio.sleep(seconds)
            await app(scope, receive, send)

        return wrapped

    return factory


@requirement("client-auth:login-time:not-counted")
async def test_auto_mode_negotiates_modern_when_the_login_far_outlasts_the_probe_deadline() -> None:
    """A login hundreds of times longer than the probe deadline still lands on the modern protocol.

    Regression lock for #3601. The server speaks both eras, so a client that gave up on the probe
    while the person was in the browser would complete `initialize` and show it on the wire.
    """
    timeline, on_request = record_timeline()

    with anyio.fail_after(LOGIN_SECONDS * 2):
        async with connect_with_oauth(
            Server("guarded"),
            provider=InMemoryAuthorizationServerProvider(),
            headless=Person(LOGIN_SECONDS),
            on_request=on_request,
            mode="auto",
        ) as (client, _):
            assert client.protocol_version == LATEST_MODERN_VERSION

    assert timeline == [(0.0, "server/discover", False), (LOGIN_SECONDS, "server/discover", True)]


@requirement("lifecycle:discover:fallback-silence")
async def test_auto_mode_falls_back_at_the_probe_deadline_when_the_server_never_answers_the_probe() -> None:
    """With nobody logging in, an unanswered probe is given up on after exactly the probe deadline.

    SDK-defined over HTTP (the spec states the timeout rule for stdio). `verify_tokens=False` leaves
    the endpoint ungated, so the provider is attached but never challenged.
    """
    timeline, on_request = record_timeline()

    with anyio.fail_after(DISCOVER_TIMEOUT_SECONDS * 2):
        async with connect_with_oauth(
            Server("guarded"),
            provider=InMemoryAuthorizationServerProvider(),
            verify_tokens=False,
            app_shim=slow_then_silent_probe(),
            on_request=on_request,
            mode="auto",
            json_response=True,
        ) as (client, headless):
            assert client.protocol_version == LATEST_HANDSHAKE_VERSION

    assert headless.authorize_urls == []
    assert timeline == [
        (0.0, "server/discover", False),
        (DISCOVER_TIMEOUT_SECONDS, "initialize", False),
        (DISCOVER_TIMEOUT_SECONDS, "notifications/initialized", False),
    ]


@requirement("client-auth:login-time:not-counted")
@requirement("lifecycle:discover:fallback-silence")
async def test_the_probe_deadline_resumes_after_the_login_with_the_budget_that_was_left() -> None:
    """A server that goes silent once the person has logged in is given up on when the rest of the deadline is spent.

    SDK-defined. Steps:
    1. The server takes 4 s to challenge the probe: 4 s of the deadline are spent.
    2. The person takes an hour: nothing is spent.
    3. The authorized probe is never answered: the client falls back when the remaining seconds are
       gone, neither at once (the login counted) nor a whole deadline later (a fresh budget).
    """
    challenge_after = 4.0
    timeline, on_request = record_timeline()

    with anyio.fail_after(LOGIN_SECONDS * 2):
        async with connect_with_oauth(
            Server("guarded"),
            provider=InMemoryAuthorizationServerProvider(),
            headless=Person(LOGIN_SECONDS),
            app_shim=slow_then_silent_probe(challenge_after=challenge_after),
            on_request=on_request,
            mode="auto",
            json_response=True,
        ) as (client, _):
            assert client.protocol_version == LATEST_HANDSHAKE_VERSION

    assert timeline == [
        (0.0, "server/discover", False),
        (challenge_after + LOGIN_SECONDS, "server/discover", True),
        (LOGIN_SECONDS + DISCOVER_TIMEOUT_SECONDS, "initialize", True),
        (LOGIN_SECONDS + DISCOVER_TIMEOUT_SECONDS, "notifications/initialized", True),
    ]


@requirement("client-auth:login-time:not-counted")
@pytest.mark.parametrize("mode", ["auto", "legacy", LATEST_MODERN_VERSION])
async def test_a_read_timeout_shorter_than_the_login_does_not_fail_the_challenged_request(mode: str) -> None:
    """Whichever request meets the 401 (the probe, `initialize`, or the first call), connecting and calling succeed.

    SDK-defined. One prompt proves the request that started the login is the one that finished it.
    """
    with anyio.fail_after(LOGIN_SECONDS * 2):
        async with connect_with_oauth(
            Server("guarded", on_list_tools=list_tools),
            provider=InMemoryAuthorizationServerProvider(),
            headless=Person(LOGIN_SECONDS),
            mode=mode,
            read_timeout_seconds=5,
            json_response=True,
        ) as (client, headless):
            result = await client.list_tools()

    assert result.tools[0].name == "echo"
    assert len(headless.authorize_urls) == 1


@requirement("client-auth:login-time:not-counted")
@pytest.mark.parametrize(
    ("hung_endpoint", "prompts", "seconds"),
    [("/register", 0, 5.0), ("/token", 1, LOGIN_SECONDS + 5.0)],
)
async def test_an_authorization_server_that_hangs_still_times_the_request_out(
    hung_endpoint: str, prompts: int, seconds: float
) -> None:
    """Only the person is off the clock: the provider's own HTTP calls, before and after the login, spend the budget.

    SDK-defined.
    """
    started = anyio.current_time()

    with anyio.fail_after(LOGIN_SECONDS * 2):
        async with connect_with_oauth(
            Server("guarded"),
            provider=InMemoryAuthorizationServerProvider(),
            headless=Person(LOGIN_SECONDS),
            app_shim=slow(hung_endpoint, math.inf),
            mode=LATEST_MODERN_VERSION,
            read_timeout_seconds=5,
        ) as (client, headless):
            with pytest.raises(MCPError) as exc_info:
                await client.list_tools()
            gave_up_after = anyio.current_time() - started

    assert exc_info.value.code == REQUEST_TIMEOUT
    assert (len(headless.authorize_urls), gave_up_after) == (prompts, seconds)


@requirement("protocol:cancel:abort-signal")
async def test_cancelling_the_caller_mid_login_abandons_the_login() -> None:
    """A suspended timeout is not a shield: cancelling the awaiting task returns at once and ends `callback_handler`.

    Pins unchanged behaviour. At 2026-07-28 abandoning a request closes its HTTP exchange, and the
    login runs inside that exchange.
    """
    person = Person(LOGIN_SECONDS)

    with anyio.fail_after(5):
        async with connect_with_oauth(
            Server("guarded"),
            provider=InMemoryAuthorizationServerProvider(),
            headless=person,
            mode=LATEST_MODERN_VERSION,
            read_timeout_seconds=5,
        ) as (client, _):
            async with anyio.create_task_group() as tg:
                tg.start_soon(client.list_tools)
                await person.in_the_browser.wait()
                tg.cancel_scope.cancel()
            await person.abandoned.wait()


@requirement("client-auth:login-time:not-counted")
@requirement("client-auth:login-time:other-requests-keep-counting")
async def test_a_login_suspends_only_the_timeout_of_the_request_that_was_challenged() -> None:
    """Of two calls with the same read timeout, the challenged one survives the login and the queued one times out.

    SDK-defined, and a known limit rather than a goal: the second call waits for the provider's
    lock, which is not counted as waiting on a person. It is sent while the server is still taking
    its 2 s over the first, so the clock the login stops is not simply the newest one.
    """
    first_call_on_the_wire = anyio.Event()
    queued_error: list[tuple[float, ErrorData]] = []

    with anyio.fail_after(LOGIN_SECONDS * 2):
        async with (
            connect_with_oauth(
                Server("guarded", on_list_tools=list_tools),
                provider=InMemoryAuthorizationServerProvider(),
                headless=Person(LOGIN_SECONDS),
                app_shim=slow("/mcp", 2),
                on_request=lambda _: first_call_on_the_wire.set(),
                mode=LATEST_MODERN_VERSION,
                read_timeout_seconds=5,
            ) as (client, _),
            anyio.create_task_group() as tg,
        ):

            async def queued_call() -> None:
                await first_call_on_the_wire.wait()
                sent_at = anyio.current_time()
                with pytest.raises(MCPError) as exc_info:
                    await client.list_tools(cache_mode="bypass")
                queued_error.append((round(anyio.current_time() - sent_at, 9), exc_info.value.error))

            tg.start_soon(queued_call)
            challenged = await client.list_tools(cache_mode="bypass")
            assert challenged.tools[0].name == "echo"

    assert queued_error == snapshot([(5.0, ErrorData(code=REQUEST_TIMEOUT, message="Request 'tools/list' timed out"))])
