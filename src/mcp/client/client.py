"""Unified MCP Client that wraps ClientSession with transport management."""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from dataclasses import KW_ONLY, dataclass, field
from typing import Any, Literal, TypeVar, cast

import anyio
import anyio.lowlevel
import mcp_types as types
from mcp_types import (
    INVALID_PARAMS,
    CacheableResult,
    CallToolResult,
    CompleteResult,
    EmptyResult,
    ErrorData,
    GetPromptResult,
    Implementation,
    InputRequest,
    InputRequiredResult,
    InputResponse,
    InputResponses,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    LoggingLevel,
    PaginatedRequestParams,
    Prompt,
    PromptReference,
    ReadResourceResult,
    RequestParamsMeta,
    Resource,
    ResourceTemplate,
    ResourceTemplateReference,
    Result,
    ServerCapabilities,
    Tool,
)
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS, MODERN_PROTOCOL_VERSIONS
from typing_extensions import deprecated

from mcp.client._input_required import DEFAULT_INPUT_REQUIRED_MAX_ROUNDS, run_input_required_driver
from mcp.client._memory import InMemoryTransport
from mcp.client._probe import negotiate_auto
from mcp.client._transport import Transport
from mcp.client.caching import CacheConfig, CacheMode, ClientResponseCache, InMemoryResponseCacheStore
from mcp.client.extension import ClaimContext, ClientExtension, NotificationBinding, ResultClaim
from mcp.client.session import (
    ClientRequestContext,
    ClientSession,
    ElicitationFnT,
    ListRootsFnT,
    LoggingFnT,
    MessageHandlerFnT,
    SamplingFnT,
)
from mcp.client.streamable_http import streamable_http_client
from mcp.client.subscriptions import ServerEvent, Subscription
from mcp.client.subscriptions import listen as _listen
from mcp.server import Server
from mcp.server.mcpserver import MCPServer
from mcp.server.runner import modern_on_request
from mcp.shared.direct_dispatcher import create_direct_dispatcher_pair
from mcp.shared.dispatcher import Dispatcher, ProgressFnT
from mcp.shared.exceptions import MCPDeprecationWarning, MCPError
from mcp.shared.extension import validate_extension_identifier
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.session import RequestResponder
from mcp.shared.subscriptions import event_to_notification

logger = logging.getLogger(__name__)

ConnectMode = Literal["legacy", "auto"] | str
"""``mode=`` value: ``"legacy"`` (initialize handshake), ``"auto"`` (discover, fall back to
initialize), or a modern protocol-version string (adopt directly). The ``str`` arm is for
forward-compat; ``Client.__post_init__`` rejects anything outside that set at construction."""

_T = TypeVar("_T")
_ResultT = TypeVar("_ResultT")
_CacheableT = TypeVar("_CacheableT", bound=CacheableResult)

_Connector = Callable[[AsyncExitStack, ConnectMode, bool], Awaitable["Dispatcher[Any]"]]
"""Resolved at ``__post_init__`` from the shape of ``server`` alone: enter whatever resources
are needed onto the exit stack and hand back the ``Dispatcher`` ``ClientSession`` will drive.
``mode`` and ``raise_exceptions`` are passed at call time so they're read at the same moment
``__aenter__`` reads them for the handshake step."""


def _connect_transport(transport: Transport) -> _Connector:
    """Connector for the stream-backed paths (URL, user-supplied ``Transport``)."""

    async def connect(exit_stack: AsyncExitStack, _mode: ConnectMode, _raise_exceptions: bool) -> Dispatcher[Any]:
        read_stream, write_stream = await exit_stack.enter_async_context(transport)
        return JSONRPCDispatcher(read_stream, write_stream)

    return connect


def _connect_inproc(server: Server[Any]) -> _Connector:
    """Connector for an in-process ``Server``: legacy mode drives the stream loop via
    ``InMemoryTransport``; any other mode drives the modern per-request path through a
    ``DirectDispatcher`` peer pair (no streams, no JSON-RPC framing, no initialize handshake)."""

    async def connect(exit_stack: AsyncExitStack, mode: ConnectMode, raise_exceptions: bool) -> Dispatcher[Any]:
        if mode == "legacy":
            transport = InMemoryTransport(server, raise_exceptions=raise_exceptions)
            read_stream, write_stream = await exit_stack.enter_async_context(transport)
            return JSONRPCDispatcher(read_stream, write_stream)
        lifespan_state = await exit_stack.enter_async_context(server.lifespan(server))
        client_disp, server_disp = create_direct_dispatcher_pair(raise_handler_exceptions=raise_exceptions)
        tg = await exit_stack.enter_async_context(anyio.create_task_group())
        exit_stack.callback(server_disp.close)
        on_request = modern_on_request(server, lifespan_state)
        await tg.start(server_disp.run, on_request, _no_inbound_client_notifications)
        return client_disp

    return connect


def _connected(value: _T | None) -> _T:
    """Narrow a post-handshake session attribute from ``T | None`` to ``T``.

    ``Client.__aenter__`` only assigns ``_session`` after the handshake succeeds, so inside
    ``async with Client(...)`` these attributes are always populated; the ``.session`` gate
    raises before this is reached otherwise. The guard exists for pyright, not runtime.
    """
    if value is None:  # pragma: no cover
        raise RuntimeError("Client must be used within an async context manager")
    return value


def _strip_userinfo(url: str) -> str:
    """Drop any userinfo from the URL's authority component; byte-exact otherwise.

    Credentials must not enter cache-key material; any further normalization could merge distinct servers.
    """
    # Pure text, no urlsplit: it strips embedded tab/CR/LF before parsing, which would misalign slices.
    sep = url.find("//")
    if sep == -1:
        return url
    start = sep + 2
    end = len(url)
    for delimiter in "/?#":
        if (found := url.find(delimiter, start)) != -1:
            end = min(end, found)
    authority = url[start:end]
    if "@" not in authority:
        return url
    return url[:start] + authority.rpartition("@")[2] + url[end:]


def _evicting_message_handler(cache: ClientResponseCache, user_handler: MessageHandlerFnT | None) -> MessageHandlerFnT:
    """Wrap the session message handler with cache eviction on server notifications."""

    async def handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, types.ServerNotification):
            try:
                await cache.evict_for_notification(message)
            except Exception:  # boundary: eviction reaches user store code; a cache fault must not block delivery
                logger.exception("Response cache eviction failed; the notification is still delivered")
        if user_handler is not None:
            await user_handler(message)
        else:
            # Mirrors ClientSession's default handler (session._default_message_handler).
            await anyio.lowlevel.checkpoint()

    return handler


def _synthesize_discover(protocol_version: str) -> types.DiscoverResult:
    return types.DiscoverResult(
        supported_versions=[protocol_version],
        capabilities=types.ServerCapabilities(),
        server_info=types.Implementation(name="", version=""),
        result_type="complete",
        ttl_ms=0,
        cache_scope="public",
    )


async def _no_inbound_client_notifications(_dctx: Any, _method: str, _params: Mapping[str, Any] | None) -> None:
    """Server-side inbound ``OnNotify`` for the modern in-process path — receives nothing.

    At 2026-07-28 the spec defines no client→server notifications: ``initialized`` and
    ``roots/list_changed`` are removed, and cancellation is structural (anyio scope cancel
    through the direct await, not a notify). Server→client notifications (progress, log
    messages) flow the other way via the per-request ``DispatchContext`` into the client's
    callbacks, and are not seen here.
    """


@dataclass(frozen=True)
class _FoldedExtensions:
    """`Client.extensions` instances folded into the shapes `ClientSession` consumes."""

    ad: dict[str, dict[str, Any]] | None
    claims: dict[str, tuple[ResultClaim[Any], ...]] | None
    bindings: tuple[NotificationBinding[Any], ...] | None
    by_model: Mapping[type[Result], ResultClaim[Any]]


def _fold_extensions(extensions: Sequence[ClientExtension] | None) -> _FoldedExtensions:
    """Fold extension contributions at construction, naming both owners on duplicate tags or methods."""
    if isinstance(extensions, Mapping):
        raise TypeError(
            "extensions= takes a sequence of ClientExtension instances. The mapping form was "
            "replaced: use advertise(identifier, settings) for advertise-only entries"
        )
    if not extensions:
        return _FoldedExtensions(ad=None, claims=None, bindings=None, by_model={})
    ad: dict[str, dict[str, Any]] = {}
    claims: dict[str, tuple[ResultClaim[Any], ...]] = {}
    bindings: list[NotificationBinding[Any]] = []
    by_model: dict[type[Result], ResultClaim[Any]] = {}
    claim_owners: dict[str, str] = {}
    binding_owners: dict[str, str] = {}
    for extension in extensions:
        identifier = getattr(extension, "identifier", None)
        if identifier is None:
            raise ValueError(
                f"{type(extension).__name__} has no `identifier`; a ClientExtension must set the "
                "`identifier` class attribute (or assign one in `__init__`) before it can be used"
            )
        validate_extension_identifier(identifier, owner=type(extension).__name__)
        if identifier in ad:
            raise ValueError(f"extension identifier {identifier!r} is passed more than once")
        ad[identifier] = extension.settings()
        extension_claims = tuple(extension.claims())
        for claim in extension_claims:
            tag = claim.result_type
            if tag in claim_owners:
                owner = claim_owners[tag]
                both = (
                    f"extension {identifier!r} claims"
                    if owner == identifier
                    else (f"extensions {owner!r} and {identifier!r} both claim")
                )
                raise ValueError(f"{both} resultType {tag!r}; a wire tag can have only one resolver")
            claim_owners[tag] = identifier
            # Each model pins its result_type Literal to one tag, so this index cannot collide.
            by_model[claim.model] = claim
        if extension_claims:
            claims[identifier] = extension_claims
        for binding in extension.notifications():
            if binding.method in binding_owners:
                owner = binding_owners[binding.method]
                both = (
                    f"extension {identifier!r} binds"
                    if owner == identifier
                    else (f"extensions {owner!r} and {identifier!r} both bind")
                )
                raise ValueError(f"{both} notification method {binding.method!r}; a method can have only one observer")
            binding_owners[binding.method] = identifier
            bindings.append(binding)
    return _FoldedExtensions(ad=ad, claims=claims or None, bindings=tuple(bindings) or None, by_model=by_model)


@dataclass
class Client:
    """A high-level MCP client for connecting to MCP servers.

    Supports in-memory transport for testing (pass a Server or MCPServer instance),
    Streamable HTTP transport (pass a URL string), or a custom Transport instance.

    Example:
        ```python
        from mcp.client import Client
        from mcp.server.mcpserver import MCPServer

        server = MCPServer("test")

        @server.tool()
        def add(a: int, b: int) -> int:
            return a + b

        async def main():
            async with Client(server) as client:
                result = await client.call_tool("add", {"a": 1, "b": 2})

        asyncio.run(main())
        ```
    """

    server: Server[Any] | MCPServer | Transport | str
    """The MCP server to connect to.

    If the server is a `Server` or `MCPServer` instance, it will be connected in-process.
    If the server is a URL string, it will be used as the URL for a `streamable_http_client` transport.
    If the server is a `Transport` instance, it will be used directly.
    """

    _: KW_ONLY

    # TODO(Marcelo): When do `raise_exceptions=True` actually raises?
    raise_exceptions: bool = False
    """Whether to raise exceptions from the server."""

    read_timeout_seconds: float | None = None
    """Timeout for read operations."""

    sampling_callback: SamplingFnT | None = None
    """Callback for handling sampling requests."""

    sampling_capabilities: types.SamplingCapability | None = None
    """Sampling sub-capabilities (e.g. tools) declared alongside `sampling_callback`; no effect without it."""

    list_roots_callback: ListRootsFnT | None = None
    """Callback for handling list roots requests."""

    logging_callback: LoggingFnT | None = None
    """Callback for handling logging notifications."""

    # TODO(Marcelo): Why do we have both "callback" and "handler"?
    message_handler: MessageHandlerFnT | None = None
    """Callback for handling raw messages."""

    client_info: Implementation | None = None
    """Client implementation info to send to server."""

    mode: ConnectMode = "auto"
    """How to negotiate the protocol version.

    'auto' (the default) probes `server/discover` and falls back to the initialize handshake on legacy servers;
    for an in-process `Server`/`MCPServer` it dispatches directly without JSON-RPC framing. 'legacy' forces the
    initialize handshake (byte-identical pre-2026 behavior). A modern protocol-version string (e.g. '2026-07-28')
    adopts that version directly without a probe — supply `prior_discover` to reuse a known DiscoverResult, or
    omit it to synthesize a minimal one."""

    prior_discover: types.DiscoverResult | None = None
    """A previously-obtained DiscoverResult to install via .adopt() when mode is a version pin.
    Ignored when mode='legacy'."""

    elicitation_callback: ElicitationFnT | None = None
    """Callback for handling elicitation requests."""

    input_required_max_rounds: int = DEFAULT_INPUT_REQUIRED_MAX_ROUNDS
    """Cap on `InputRequiredResult` retry rounds before `call_tool` / `get_prompt` /
    `read_resource` give up. Use `client.session.<method>(..., allow_input_required=True)`
    to drive the loop manually instead."""

    extensions: Sequence[ClientExtension] | None = None
    """Opt-in client extensions (SEP-2133).

    Each instance contributes its capability ad, its result claims (resolved
    transparently by `call_tool`), and its notification bindings. For an
    ad-only entry use `mcp.client.advertise(identifier, settings)`."""

    cache: CacheConfig | Literal[False] | None = None
    """Client-side response caching for the SEP-2549 cacheable methods (2026-07-28).

    `None` (the default) honors server `ttlMs`/`cacheScope` hints with a per-client
    in-memory store; pass a `CacheConfig` to customize, or `False` to disable. The
    cacheable verbs take a per-call `cache_mode` (see `CacheMode`); calls carrying
    `meta` always reach the server. A `CacheConfig` with a custom `store` requires
    `target_id` when the server is not a URL (no identity can be derived)."""

    _entered: bool = field(init=False, default=False)
    _session: ClientSession | None = field(init=False, default=None)
    _exit_stack: AsyncExitStack | None = field(init=False, default=None)
    _connect: _Connector = field(init=False, repr=False, compare=False)
    _response_cache: ClientResponseCache | None = field(init=False, default=None, repr=False, compare=False)
    _folded_extensions: _FoldedExtensions = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.mode not in ("legacy", "auto") and self.mode not in MODERN_PROTOCOL_VERSIONS:
            hint = (
                f" ({self.mode!r} is a handshake-era version; use mode='legacy')"
                if self.mode in HANDSHAKE_PROTOCOL_VERSIONS
                else ""
            )
            raise ValueError(
                f"mode must be 'legacy', 'auto', or one of {list(MODERN_PROTOCOL_VERSIONS)}; got {self.mode!r}{hint}"
            )

        self._folded_extensions = _fold_extensions(self.extensions)

        srv = self.server
        if isinstance(srv, MCPServer):
            srv = srv._lowlevel_server  # pyright: ignore[reportPrivateUsage]
        if isinstance(srv, Server):
            self._connect = _connect_inproc(srv)
        elif isinstance(srv, str):
            self._connect = _connect_transport(streamable_http_client(srv))
        else:
            self._connect = _connect_transport(srv)

        if self.cache is not False:
            config = self.cache if self.cache is not None else CacheConfig()
            # Only the hash below leaves this scope - the raw identity may carry credentials; never log or store it.
            target_id = config.target_id
            if target_id is None and isinstance(self.server, str):
                target_id = _strip_userinfo(self.server)
            if target_id is None:
                if config.store is not None:
                    raise ValueError(
                        "a custom cache store requires CacheConfig.target_id when the server is not a URL: "
                        "in-process servers and Transport instances get a random per-client identity, so "
                        "their entries in a shared store could never be served to another client"
                    )
                target_id = uuid.uuid4().hex
            self._response_cache = ClientResponseCache(
                store=config.store if config.store is not None else InMemoryResponseCacheStore(),
                partition=config.partition,
                arm_id=hashlib.sha256(target_id.encode()).hexdigest(),
                default_ttl_ms=config.default_ttl_ms,
                clock=config.clock,
                share_public=config.share_public,
                # Lazy: the negotiated version is unknown until __aenter__'s handshake.
                negotiated_version=lambda: self._session.protocol_version if self._session is not None else None,
            )

    async def _build_session(self, exit_stack: AsyncExitStack) -> ClientSession:
        """Enter the resolved connector and return an un-entered ClientSession."""
        dispatcher = await self._connect(exit_stack, self.mode, self.raise_exceptions)
        message_handler = self.message_handler
        if self._response_cache is not None:
            message_handler = _evicting_message_handler(self._response_cache, self.message_handler)
        return ClientSession(
            dispatcher=dispatcher,
            read_timeout_seconds=self.read_timeout_seconds,
            sampling_callback=self.sampling_callback,
            sampling_capabilities=self.sampling_capabilities,
            list_roots_callback=self.list_roots_callback,
            logging_callback=self.logging_callback,
            message_handler=message_handler,
            client_info=self.client_info,
            elicitation_callback=self.elicitation_callback,
            extensions=self._folded_extensions.ad,
            result_claims=self._folded_extensions.claims,
            notification_bindings=self._folded_extensions.bindings,
        )

    async def __aenter__(self) -> Client:
        """Enter the async context manager."""
        if self._entered:
            raise RuntimeError("Client is already entered; cannot reenter")
        self._entered = True

        async with AsyncExitStack() as exit_stack:
            session = await self._build_session(exit_stack)
            session = await exit_stack.enter_async_context(session)

            if self.mode == "legacy":
                await session.initialize()
            elif self.mode == "auto":
                await negotiate_auto(session)
            else:
                session.adopt(self.prior_discover or _synthesize_discover(self.mode))

            # Only publish the session after the handshake succeeds, so `_session is not None`
            # implies the protocol_version/server_info/server_capabilities are populated. If the
            # handshake raised above, the local exit_stack unwinds the transport for us.
            self._session = session
            self._exit_stack = exit_stack.pop_all()
            return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> None:
        """Exit the async context manager."""
        if self._exit_stack:  # pragma: no branch
            await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)
        self._session = None

    @property
    def session(self) -> ClientSession:
        """Get the underlying ClientSession.

        This provides access to the full ClientSession API for advanced use cases.

        Raises:
            RuntimeError: If accessed before entering the context manager.
        """
        if self._session is None:
            raise RuntimeError("Client must be used within an async context manager")
        return self._session

    # TODO(maxisbey): the by-construction shape is for __aenter__ to return a connected-view
    # type whose protocol_version/server_info/server_capabilities are non-Optional fields,
    # eliminating these guards (and the one in .session). Same family as resolving the
    # transport/connector at __post_init__ so the Optional internal fields disappear.
    @property
    def protocol_version(self) -> str:
        """Negotiated protocol version (set by initialize/discover/adopt during ``__aenter__``)."""
        return _connected(self.session.protocol_version)

    @property
    def server_info(self) -> Implementation:
        """Server name/version (set by initialize/discover/adopt during ``__aenter__``)."""
        return _connected(self.session.server_info)

    @property
    def server_capabilities(self) -> ServerCapabilities:
        """Server capabilities (set by initialize/discover/adopt during ``__aenter__``)."""
        return _connected(self.session.server_capabilities)

    @property
    def instructions(self) -> str | None:
        """Server-provided instructions text, if any."""
        return self.session.instructions

    @deprecated(
        "ping is removed as of 2026-07-28; the method only works under mode='legacy'.",
        category=MCPDeprecationWarning,
    )
    async def send_ping(self, *, meta: RequestParamsMeta | None = None) -> EmptyResult:
        """Send a ping request to the server."""
        return await self.session.send_ping(meta=meta)

    @deprecated(
        "Client-to-server progress is deprecated as of 2026-07-28; progress is server-to-client only.",
        category=MCPDeprecationWarning,
    )
    async def send_progress_notification(
        self,
        progress_token: str | int,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        """Send a progress notification to the server."""
        await self.session.send_progress_notification(  # pyright: ignore[reportDeprecated]
            progress_token=progress_token,
            progress=progress,
            total=total,
            message=message,
        )

    @deprecated("The logging capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def set_logging_level(self, level: LoggingLevel, *, meta: RequestParamsMeta | None = None) -> EmptyResult:
        """Set the logging level on the server."""
        return await self.session.set_logging_level(level=level, meta=meta)  # pyright: ignore[reportDeprecated]

    async def _cached_fetch(
        self,
        method: str,
        *,
        cursor: str | None,
        meta: RequestParamsMeta | None,
        cache_mode: CacheMode,
        send: Callable[[], Awaitable[_CacheableT]],
        absorb: Callable[[_CacheableT], _CacheableT] | None = None,
    ) -> _CacheableT:
        """Serve one of the four list verbs through the response cache.

        `absorb` (tools/list only) re-applies session-side derived state to a served cache hit.
        """
        cache = self._response_cache
        if cache is None or cache_mode == "bypass":
            return await send()
        # A closed (or never-entered) client must raise, never serve cached entries.
        _ = self.session
        if meta is not None and cache_mode == "use":
            # meta (a progress token, tracing fields) expects a wire request; fetch and replace the entry.
            cache_mode = "refresh"
        if cursor is not None:
            # Continuation pages skip the cache, but an expired cursor means the listing changed (spec SHOULD evict).
            try:
                return await send()
            except MCPError as e:
                if e.code == INVALID_PARAMS:
                    await cache.evict_method(method)
                raise
        if cache_mode == "use" and (hit := await cache.read(method, "")) is not None:
            # The hit is a private deep copy, so absorption may mutate it freely.
            served = cast(_CacheableT, hit)
            return served if absorb is None else absorb(served)
        gen = cache.capture(method, "")
        result = await send()
        await cache.write(method, "", result, gen, cache_mode)
        return result

    async def list_resources(
        self,
        *,
        cursor: str | None = None,
        meta: RequestParamsMeta | None = None,
        cache_mode: CacheMode = "use",
    ) -> ListResourcesResult:
        """List a single page of available resources from the server.

        Returns one page only. The result may include a `next_cursor` if more
        pages are available. Use `list_all_resources` to drain every page.
        """
        return await self._cached_fetch(
            "resources/list",
            cursor=cursor,
            meta=meta,
            cache_mode=cache_mode,
            send=lambda: self.session.list_resources(params=PaginatedRequestParams(cursor=cursor, _meta=meta)),
        )

    async def list_resource_templates(
        self,
        *,
        cursor: str | None = None,
        meta: RequestParamsMeta | None = None,
        cache_mode: CacheMode = "use",
    ) -> ListResourceTemplatesResult:
        """List a single page of available resource templates from the server.

        Returns one page only. The result may include a `next_cursor` if more
        pages are available. Use `list_all_resource_templates` to drain every
        page.
        """
        return await self._cached_fetch(
            "resources/templates/list",
            cursor=cursor,
            meta=meta,
            cache_mode=cache_mode,
            send=lambda: self.session.list_resource_templates(params=PaginatedRequestParams(cursor=cursor, _meta=meta)),
        )

    async def read_resource(
        self,
        uri: str,
        *,
        input_responses: InputResponses | None = None,
        request_state: str | None = None,
        meta: RequestParamsMeta | None = None,
        cache_mode: CacheMode = "use",
    ) -> ReadResourceResult:
        """Read a resource from the server.

        If the server returns an `InputRequiredResult`, the embedded input
        requests are dispatched to this client's sampling / elicitation / roots
        callbacks and the read is retried automatically (up to
        `input_required_max_rounds`).

        Args:
            uri: The URI of the resource to read.
            input_responses: Responses to seed the first call with (e.g. when
                resuming from a persisted `InputRequiredResult`).
            request_state: Opaque state to seed the first call with.
            meta: Additional metadata for the request.
            cache_mode: Cache behavior for this call (see `CacheMode`); seeded
                calls (`input_responses` or `request_state` set) ignore it.

        Returns:
            The resource content.

        Raises:
            InputRequiredRoundsExceededError: `input_required_max_rounds` exhausted.
            MCPError: A callback returned `ErrorData` for an embedded input request.
            pydantic.ValidationError: The server returned a result that does not
                conform to the negotiated protocol version.
        """

        async def retry(r: InputResponses | None, s: str | None) -> ReadResourceResult | InputRequiredResult:
            return await self.session.read_resource(
                uri, input_responses=r, request_state=s, meta=meta, allow_input_required=True
            )

        # Seeded calls resume a specific exchange and must never be cached (spec MUST).
        seeded = input_responses is not None or request_state is not None
        cache = None if seeded else self._response_cache
        if cache is None or cache_mode == "bypass":
            return await self._drive_input_required(await retry(input_responses, request_state), retry)
        # A closed (or never-entered) client must raise, never serve cached entries.
        _ = self.session
        if meta is not None and cache_mode == "use":
            # Calls carrying meta always reach the server (mirrors `_cached_fetch`).
            cache_mode = "refresh"
        if cache_mode == "use" and (hit := await cache.read("resources/read", uri)) is not None:
            # Only terminal first-round results are stored, so a hit legitimately skips the driver.
            return cast(ReadResourceResult, hit)
        gen = cache.capture("resources/read", uri)
        first = await retry(None, None)
        if not isinstance(first, InputRequiredResult):
            await cache.write("resources/read", uri, first, gen, cache_mode)
        elif cache_mode == "refresh":
            # The refresh superseded whatever was cached, but an input_required resolution
            # cannot be stored: purge the warm entry so it cannot be served again.
            await cache.evict_key("resources/read", uri)
        # Driver rounds carry inputResponses, so a terminal result reached through them is never cached (spec MUST).
        return await self._drive_input_required(first, retry)

    def listen(
        self,
        *,
        tools_list_changed: bool = False,
        prompts_list_changed: bool = False,
        resources_list_changed: bool = False,
        resource_subscriptions: Sequence[str] = (),
    ) -> AbstractAsyncContextManager[Subscription]:
        """Open a `subscriptions/listen` stream of typed change events (2026-07-28 only).

        Keyword args mirror the wire `SubscriptionFilter`; entering waits for the ack (honored subset: `sub.honored`):

            async with client.listen(tools_list_changed=True) as sub:
                async for event in sub:
                    tools = await client.list_tools()  # refetch on change

        A graceful close ends the loop; an abrupt drop raises `SubscriptionLost`. No replay: re-listen and refetch.

        Raises:
            ListenNotSupportedError: The negotiated protocol version predates 2026-07-28.
            MCPError: The server rejected the request or the connection failed first.
            SubscriptionLost: The stream ended before it was acknowledged.
            TimeoutError: The read timeout elapsed before the acknowledgment.
        """
        return _listen(
            self.session,
            tools_list_changed=tools_list_changed,
            prompts_list_changed=prompts_list_changed,
            resources_list_changed=resources_list_changed,
            resource_subscriptions=resource_subscriptions,
            on_event=self._evict_for_listen_event if self._response_cache is not None else None,
        )

    async def _evict_for_listen_event(self, event: ServerEvent) -> None:
        """Finish response-cache eviction before a listen consumer can refetch.

        Without it the iterator wakes first and refetches a still-warm entry, with no
        corrective wake (events are deduplicated level triggers). The tee path repeats
        the eviction; deliberate: idempotent, and it covers non-iterating consumers.
        """
        cache = self._response_cache
        assert cache is not None  # installed as the event barrier only when a cache exists
        try:
            await cache.evict_for_notification(event_to_notification(event, {}))
        except Exception:  # boundary: eviction reaches user store code; a cache fault must not block delivery
            logger.exception("Response cache eviction failed; the event is still delivered")

    @deprecated(
        "resources/subscribe is removed as of 2026-07-28; use Client.listen() instead.",
        category=MCPDeprecationWarning,
    )
    async def subscribe_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> EmptyResult:
        """Subscribe to resource updates (2025-era servers only)."""
        return await self.session.subscribe_resource(uri, meta=meta)  # pyright: ignore[reportDeprecated]

    @deprecated(
        "resources/unsubscribe is removed as of 2026-07-28; use Client.listen() instead.",
        category=MCPDeprecationWarning,
    )
    async def unsubscribe_resource(self, uri: str, *, meta: RequestParamsMeta | None = None) -> EmptyResult:
        """Unsubscribe from resource updates (2025-era servers only)."""
        return await self.session.unsubscribe_resource(uri, meta=meta)  # pyright: ignore[reportDeprecated]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: float | None = None,
        progress_callback: ProgressFnT | None = None,
        *,
        input_responses: InputResponses | None = None,
        request_state: str | None = None,
        meta: RequestParamsMeta | None = None,
    ) -> CallToolResult:
        """Call a tool on the server.

        If the server returns an `InputRequiredResult`, the embedded input
        requests are dispatched to this client's sampling / elicitation / roots
        callbacks and the call is retried automatically (up to
        `input_required_max_rounds`). To drive the loop yourself — e.g. to
        persist `request_state` across process restarts — use
        `client.session.call_tool(..., allow_input_required=True)`. Persisted
        state is still subject to the server's TTL, request binding, and key
        lifetime; a server on the default process-local key rejects it after a restart.

        Result shapes claimed by this client's `extensions` are finished by the
        owning claim's resolver, whose `CallToolResult` is returned; resolver
        exceptions propagate as-is. To receive the claimed shape yourself, use
        `client.session.call_tool(..., allow_claimed=True)`.

        Args:
            name: The name of the tool to call.
            arguments: Arguments to pass to the tool.
            read_timeout_seconds: Timeout for each underlying `tools/call` round.
            progress_callback: Callback for progress updates.
            input_responses: Responses to seed the first call with (e.g. when
                resuming from a persisted `InputRequiredResult`).
            request_state: Opaque state to seed the first call with.
            meta: Additional metadata for the request.

        Returns:
            The tool result.

        Raises:
            InputRequiredRoundsExceededError: `input_required_max_rounds` exhausted.
            MCPError: A callback returned `ErrorData` for an embedded input request.
            pydantic.ValidationError: The server returned a result that does not
                conform to the negotiated protocol version.
        """

        async def retry(r: InputResponses | None, s: str | None) -> CallToolResult | InputRequiredResult | Result:
            return await self.session.call_tool(
                name,
                arguments,
                read_timeout_seconds=read_timeout_seconds,
                progress_callback=progress_callback,
                input_responses=r,
                request_state=s,
                meta=meta,
                allow_input_required=True,
                # Input rounds resolve before a claimed result, so a claim may end any round.
                allow_claimed=True,
            )

        result = await self._drive_input_required(await retry(input_responses, request_state), retry)
        if isinstance(result, CallToolResult):
            return result
        # Only claimed shapes reach this point, so the lookup is total.
        claim = self._folded_extensions.by_model[type(result)]
        final = await claim.resolve(
            result,
            ClaimContext(session=self.session, tool_name=name, read_timeout_seconds=read_timeout_seconds),
        )
        if not final.is_error:
            # Match the direct path: revalidate the output schema, but never for isError results.
            await self.session.validate_tool_result(name, final)
        return final

    async def list_prompts(
        self,
        *,
        cursor: str | None = None,
        meta: RequestParamsMeta | None = None,
        cache_mode: CacheMode = "use",
    ) -> ListPromptsResult:
        """List a single page of available prompts from the server.

        Returns one page only. The result may include a `next_cursor` if more
        pages are available. Use `list_all_prompts` to drain every page.
        """
        return await self._cached_fetch(
            "prompts/list",
            cursor=cursor,
            meta=meta,
            cache_mode=cache_mode,
            send=lambda: self.session.list_prompts(params=PaginatedRequestParams(cursor=cursor, _meta=meta)),
        )

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str] | None = None,
        *,
        input_responses: InputResponses | None = None,
        request_state: str | None = None,
        meta: RequestParamsMeta | None = None,
    ) -> GetPromptResult:
        """Get a prompt from the server.

        If the server returns an `InputRequiredResult`, the embedded input
        requests are dispatched to this client's sampling / elicitation / roots
        callbacks and the get is retried automatically (up to
        `input_required_max_rounds`).

        Args:
            name: The name of the prompt.
            arguments: Arguments to pass to the prompt.
            input_responses: Responses to seed the first call with (e.g. when
                resuming from a persisted `InputRequiredResult`).
            request_state: Opaque state to seed the first call with.
            meta: Additional metadata for the request.

        Returns:
            The prompt content.

        Raises:
            InputRequiredRoundsExceededError: `input_required_max_rounds` exhausted.
            MCPError: A callback returned `ErrorData` for an embedded input request.
            pydantic.ValidationError: The server returned a result that does not
                conform to the negotiated protocol version.
        """

        async def retry(r: InputResponses | None, s: str | None) -> GetPromptResult | InputRequiredResult:
            return await self.session.get_prompt(
                name, arguments, input_responses=r, request_state=s, meta=meta, allow_input_required=True
            )

        return await self._drive_input_required(await retry(input_responses, request_state), retry)

    async def _drive_input_required(
        self,
        first: _ResultT | InputRequiredResult,
        retry: Callable[[InputResponses | None, str | None], Awaitable[_ResultT | InputRequiredResult]],
    ) -> _ResultT:
        """Hand an `InputRequiredResult` to the SEP-2322 driver, or pass a terminal result through.

        `dispatch` routes each embedded request through the same callback table
        that serves legacy server→client RPCs, so the two paths stay
        behaviourally identical by construction.
        """
        if not isinstance(first, InputRequiredResult):
            return first
        session = self.session

        async def dispatch(key: str, req: InputRequest) -> InputResponse | ErrorData:
            ctx = ClientRequestContext(session=session, request_id=key, meta=req.params.meta if req.params else None)
            return await session.dispatch_input_request(ctx, req)

        return await run_input_required_driver(
            first, dispatch=dispatch, retry=retry, max_rounds=self.input_required_max_rounds
        )

    async def complete(
        self,
        ref: ResourceTemplateReference | PromptReference,
        argument: dict[str, str],
        context_arguments: dict[str, str] | None = None,
    ) -> CompleteResult:
        """Get completions for a prompt or resource template argument.

        Args:
            ref: Reference to the prompt or resource template
            argument: The argument to complete
            context_arguments: Additional context arguments

        Returns:
            Completion suggestions.
        """
        return await self.session.complete(ref=ref, argument=argument, context_arguments=context_arguments)

    async def list_tools(
        self,
        *,
        cursor: str | None = None,
        meta: RequestParamsMeta | None = None,
        cache_mode: CacheMode = "use",
    ) -> ListToolsResult:
        """List a single page of available tools from the server.

        Returns one page only. The result may include a `next_cursor` if more
        pages are available. Use `list_all_tools` to drain every page.
        """
        return await self._cached_fetch(
            "tools/list",
            cursor=cursor,
            meta=meta,
            cache_mode=cache_mode,
            send=lambda: self.session.list_tools(params=PaginatedRequestParams(cursor=cursor, _meta=meta)),
            # A cache hit skips session.list_tools, so the session re-absorbs the served
            # listing to rebuild its derived per-tool state. Hits are cursorless, but a
            # cached page 1 can carry next_cursor - never prune on a partial listing.
            absorb=lambda hit: self.session._absorb_tool_listing(  # pyright: ignore[reportPrivateUsage]
                hit, complete=hit.next_cursor is None
            ),
        )

    async def iter_all_tools(self, *, meta: RequestParamsMeta | None = None) -> AsyncIterator[Tool]:
        """Yield every tool from the server, paging through `next_cursor`.

        Useful for streaming consumers that want to process tools without
        materializing the full list in memory.
        """
        cursor: str | None = None
        while True:
            result = await self.list_tools(cursor=cursor, meta=meta)
            for tool in result.tools:
                yield tool
            if result.next_cursor is None:
                return
            cursor = result.next_cursor

    async def list_all_tools(self, *, meta: RequestParamsMeta | None = None) -> list[Tool]:
        """List every tool from the server, draining `next_cursor` across pages.

        Unlike `list_tools`, which returns one page, this walks pagination
        until the server reports no further pages and returns the combined
        list.
        """
        return [tool async for tool in self.iter_all_tools(meta=meta)]

    async def iter_all_prompts(self, *, meta: RequestParamsMeta | None = None) -> AsyncIterator[Prompt]:
        """Yield every prompt from the server, paging through `next_cursor`."""
        cursor: str | None = None
        while True:
            result = await self.list_prompts(cursor=cursor, meta=meta)
            for prompt in result.prompts:
                yield prompt
            if result.next_cursor is None:
                return
            cursor = result.next_cursor

    async def list_all_prompts(self, *, meta: RequestParamsMeta | None = None) -> list[Prompt]:
        """List every prompt from the server, draining `next_cursor` across pages."""
        return [prompt async for prompt in self.iter_all_prompts(meta=meta)]

    async def iter_all_resources(self, *, meta: RequestParamsMeta | None = None) -> AsyncIterator[Resource]:
        """Yield every resource from the server, paging through `next_cursor`."""
        cursor: str | None = None
        while True:
            result = await self.list_resources(cursor=cursor, meta=meta)
            for resource in result.resources:
                yield resource
            if result.next_cursor is None:
                return
            cursor = result.next_cursor

    async def list_all_resources(self, *, meta: RequestParamsMeta | None = None) -> list[Resource]:
        """List every resource from the server, draining `next_cursor` across pages."""
        return [resource async for resource in self.iter_all_resources(meta=meta)]

    async def iter_all_resource_templates(
        self, *, meta: RequestParamsMeta | None = None
    ) -> AsyncIterator[ResourceTemplate]:
        """Yield every resource template from the server, paging through `next_cursor`."""
        cursor: str | None = None
        while True:
            result = await self.list_resource_templates(cursor=cursor, meta=meta)
            for template in result.resource_templates:
                yield template
            if result.next_cursor is None:
                return
            cursor = result.next_cursor

    async def list_all_resource_templates(self, *, meta: RequestParamsMeta | None = None) -> list[ResourceTemplate]:
        """List every resource template from the server, draining `next_cursor` across pages."""
        return [template async for template in self.iter_all_resource_templates(meta=meta)]

    @deprecated("The roots capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def send_roots_list_changed(self) -> None:
        """Send a notification that the roots list has changed."""
        # TODO(Marcelo): Currently, there is no way for the server to handle this. We should add support.
        await self.session.send_roots_list_changed()  # pyright: ignore[reportDeprecated]
