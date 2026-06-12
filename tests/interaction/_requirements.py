"""Requirements manifest for the interaction-model test suite.

Every user-facing behaviour the SDK must satisfy, keyed by a stable `<area>:<feature>[:<variant>]`
ID. Each entry owns the tests that exercise it: tests declare `@requirement("<id>")` (a test that
proves several behaviours stacks several decorators) and `test_coverage.py` enforces the contract
in both directions: every non-deferred requirement has at least one test, and every test carries
at least one requirement.

Sources:
    spec URL    -- externally mandated by the MCP specification (deep link to the section)
    `sdk`       -- a behavioural guarantee the SDK chose; not spec-mandated
    `issue:#n`  -- regression lock-in for a previously fixed bug

The `behavior` sentence describes the REQUIRED behaviour -- what the specification (or the SDK's
own contract) says should happen. Tests always pin the SDK's current behaviour. Where current
behaviour falls short of `behavior`, the gap is recorded as data: `divergence` on entries whose
tests pin the divergent behaviour, or `deferred` on entries that are tracked but not yet covered
by a test in this suite. An entry may carry both: `divergence` records the spec-compliance gap
(issue-able) and `deferred` records why no test exists; `divergence` alone implies a test pins
the divergent behaviour. `issue` carries the tracking link for a recorded gap once one is filed.

`deferred` reasons take one of three shapes: where the behaviour is exercised elsewhere in this
repo the reason names the covering test path; where the SDK does not implement the behaviour at
all the reason starts with "Not implemented in the SDK"; and where an interaction-level test is
planned but not yet written the reason starts with "Not yet covered here".

`transports` records which transports a behaviour applies to (or is observable on); None means
the behaviour is transport-independent.

The ID vocabulary and entry granularity are aligned with the TypeScript SDK's end-to-end
requirements suite, so coverage and recorded divergences can be compared across the two SDKs
entry by entry; IDs that exist in only one SDK reflect genuinely different API surface.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypeVar

import pytest

SPEC_REVISION = "2025-11-25"
SPEC_BASE_URL = f"https://modelcontextprotocol.io/specification/{SPEC_REVISION}"

Transport = Literal["in-memory", "stdio", "streamable-http", "sse"]

_TestFn = TypeVar("_TestFn", bound=Callable[..., object])

_SOURCE_PATTERN = re.compile(r"https://modelcontextprotocol\.io/specification/.+|sdk|issue:#\d+")

_TASKS_DEFERRAL = (
    "Tasks have been removed from the draft spec and from this SDK; they are expected to return "
    "as a separate MCP extension. These 2025-11-25 requirements are tracked but intentionally "
    "unimplemented."
)


@dataclass(frozen=True, kw_only=True)
class Divergence:
    """A documented gap between the SDK behaviour this suite pins and what `source` mandates."""

    note: str
    issue: str | None = None


@dataclass(frozen=True, kw_only=True)
class Requirement:
    """A single testable behaviour and the provenance of why it must hold."""

    source: str
    behavior: str
    transports: tuple[Transport, ...] | None = None
    divergence: Divergence | None = None
    deferred: str | None = None
    issue: str | None = None

    def __post_init__(self) -> None:
        if not _SOURCE_PATTERN.fullmatch(self.source):
            raise ValueError(f"source must be a specification URL, 'sdk', or 'issue:#n', got {self.source!r}")


REQUIREMENTS: dict[str, Requirement] = {
    # ═══════════════════════════════════════════════════════════════════════════
    # Lifecycle & version negotiation
    # ═══════════════════════════════════════════════════════════════════════════
    "lifecycle:capability:client-not-declared": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#operation",
        behavior=(
            "The client rejects sending notifications or registering handlers for capabilities it did not declare."
        ),
        divergence=Divergence(
            note=(
                "The client does not check its own declared capabilities before sending notifications or "
                "serving callbacks; nothing prevents a caller from violating the spec's MUST."
            ),
        ),
        deferred=(
            "Not implemented in the SDK: the client does not check its own declared capabilities before "
            "sending notifications or serving callbacks."
        ),
    ),
    "lifecycle:capability:server-not-advertised": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#operation",
        behavior=(
            "The client rejects calls to methods (e.g. resources/list) for capabilities the server did not advertise."
        ),
        divergence=Divergence(
            note=(
                "The client sends any request regardless of the server's advertised capabilities and "
                "surfaces whatever the server answers; the spec's MUST is not enforced."
            ),
        ),
        deferred=(
            "Not implemented in the SDK: the client sends any request regardless of the server's "
            "advertised capabilities and surfaces whatever the server answers."
        ),
    ),
    "lifecycle:initialize:basic": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#initialization",
        behavior=(
            "Connecting sends initialize with the protocol version, client capabilities, and client "
            "info; the server responds with its own and the connection is established."
        ),
    ),
    "lifecycle:initialize:server-info": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#initialization",
        behavior="The initialize result identifies the server: name and version, plus title when declared.",
    ),
    "lifecycle:initialize:instructions": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#initialization",
        behavior="A server may include an instructions string in the initialize result; the client exposes it.",
    ),
    "lifecycle:initialize:capabilities:from-handlers": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#capability-negotiation",
        behavior=(
            "The server advertises a capability for each feature area it has a registered handler for, "
            "and omits the capability for areas it does not."
        ),
    ),
    "lifecycle:initialize:capabilities:minimal": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#capability-negotiation",
        behavior="A server with no feature handlers advertises no feature capabilities.",
    ),
    "lifecycle:initialize:client-info": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#initialization",
        behavior="The client's name, version, and title are visible to server handlers after initialization.",
    ),
    "lifecycle:initialize:client-capabilities": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#capability-negotiation",
        behavior=(
            "The client capabilities visible to the server reflect which client callbacks are configured "
            "(sampling, elicitation, roots)."
        ),
    ),
    "lifecycle:initialized-notification": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#initialization",
        behavior=(
            "After successful initialization, the client sends exactly one initialized notification, "
            "before any non-ping request."
        ),
    ),
    "lifecycle:ping": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/ping#behavior-requirements",
        behavior="ping in either direction returns an empty result.",
    ),
    "ping:client-to-server": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/ping#behavior-requirements",
        behavior="A client-initiated ping receives an empty result from the server.",
    ),
    "ping:server-to-client": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/ping#behavior-requirements",
        behavior="A server-initiated ping receives an empty result from the client.",
    ),
    "lifecycle:requests-before-initialized": Requirement(
        source="sdk",
        behavior=(
            "A request other than ping sent before the initialization handshake completes is rejected with an error."
        ),
    ),
    "lifecycle:pre-initialization-ordering": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#initialization",
        behavior=(
            "Before initialization completes, the client sends no requests other than pings, and the "
            "server sends no requests other than pings and logging."
        ),
        divergence=Divergence(
            note=(
                "The server's send methods (create_message / elicit_form / list_roots) do not check "
                "initialization state before sending; on the client side, Client always completes the "
                "handshake before any caller code runs."
            ),
        ),
        deferred=(
            "Not implemented in the SDK: neither side enforces sender-side restraint. The server's send "
            "methods (create_message / elicit_form / list_roots) do not check initialization state before "
            "sending, and there is no natural hook to issue a server-to-client request between the "
            "initialize response and the initialized notification through the public API; on the client "
            "side, Client always completes the handshake before any caller code runs."
        ),
    ),
    "lifecycle:version:downgrade": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#version-negotiation",
        behavior=(
            "When the server returns an older supported protocol version, the client downgrades to it "
            "and the connection succeeds at that version."
        ),
    ),
    "lifecycle:version:match": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#version-negotiation",
        behavior=(
            "When the server supports the requested protocol version it echoes that version in the "
            "initialize result, and the connection proceeds at that version."
        ),
    ),
    "lifecycle:version:server-fallback-latest": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#version-negotiation",
        behavior=(
            "An initialize request carrying a protocol version the server does not support is answered "
            "with another version the server supports — the latest one — rather than an error."
        ),
    ),
    "lifecycle:version:reject-unsupported": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#version-negotiation",
        behavior=(
            "A client that receives an initialize response carrying a protocol version it does not "
            "support fails initialization with an error rather than proceeding with the session."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Protocol primitives: cancellation, timeout, progress, errors, _meta
    # ═══════════════════════════════════════════════════════════════════════════
    "protocol:request-id:unique": Requirement(
        source=f"{SPEC_BASE_URL}/basic#requests",
        behavior=(
            "Every request sent on a session carries a unique, non-null string or integer id; ids are "
            "never reused within the session."
        ),
    ),
    "protocol:notifications:no-response": Requirement(
        source=f"{SPEC_BASE_URL}/basic#notifications",
        behavior=(
            "Notifications are never answered: every message the server delivers is either the response "
            "to a request the client sent or a notification carrying no id."
        ),
    ),
    "protocol:cancel:abort-signal": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/cancellation#cancellation-flow",
        behavior=(
            "Cancelling an in-flight request through the client API sends notifications/cancelled with "
            "the request id and fails the local call."
        ),
        deferred=(
            "Not implemented in the SDK: there is no public client-side API to cancel an in-flight "
            "request; cancellation requires hand-constructing the notification (which is how "
            "protocol:cancel:in-flight exercises the receiving side)."
        ),
    ),
    "protocol:cancel:handler-abort-propagates": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/cancellation#behavior-requirements",
        behavior="On the receiving side, a cancellation notification stops the running request handler.",
    ),
    "protocol:cancel:in-flight": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/cancellation#behavior-requirements",
        behavior=(
            "A cancellation notification for an in-flight request stops the server-side handler, and the "
            "receiver does not send a response for the cancelled request."
        ),
        divergence=Divergence(
            note=(
                "The spec says receivers of a cancellation SHOULD NOT send a response for the cancelled "
                "request; the server sends an error response (code 0, 'Request cancelled'), which is what "
                "unblocks the SDK client's pending call."
            ),
        ),
    ),
    "protocol:cancel:initialize-not-cancellable": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/cancellation#behavior-requirements",
        behavior="The client never sends notifications/cancelled for the initialize request.",
        deferred=(
            "Not implemented in the SDK: the client has no public cancellation API at all, so no pathway "
            "exists that could cancel initialize; there is no distinct behaviour to pin beyond that absence."
        ),
    ),
    "protocol:cancel:late-response-ignored": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/cancellation#behavior-requirements",
        behavior=(
            "A response that arrives after the sender issued notifications/cancelled is ignored; the "
            "request stays failed and no error is raised."
        ),
        divergence=Divergence(
            note=(
                "A response whose id matches no in-flight request is delivered to the message handler "
                "as a RuntimeError rather than being silently ignored. The post-cancellation case is the "
                "same code path; tested in its unknown-id form because that is deterministic without the "
                "client-side cancellation API the SDK does not yet provide."
            ),
        ),
    ),
    "protocol:cancel:server-survives": Requirement(
        source="sdk",
        behavior="The session continues to serve new requests after an earlier request was cancelled.",
    ),
    "protocol:cancel:server-to-client": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/cancellation#behavior-requirements",
        behavior=(
            "A server that abandons an in-flight server-initiated request (sampling, elicitation, roots) "
            "cancels it, and the client stops processing the cancelled request."
        ),
        divergence=Divergence(
            note=(
                "Abandoning a server-side send_request emits no cancellation notification, and the client "
                "could not act on one anyway: client callbacks run inline in the receive loop, so a "
                "cancellation is not even read until the callback has finished."
            ),
        ),
        deferred=(
            "Not implemented in the SDK: abandoning a server-side send_request emits no cancellation "
            "notification (the same sender-side gap recorded on protocol:timeout:sends-cancellation), and "
            "the client could not act on one anyway because client callbacks run inline in the receive "
            "loop, so a cancellation would not even be read until the callback had already finished."
        ),
    ),
    "protocol:cancel:unknown-id-ignored": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/cancellation#error-handling",
        behavior=(
            "The receiver silently ignores a cancellation notification referencing an unknown or "
            "already-completed request id; no error response is sent and no exception is raised."
        ),
    ),
    "protocol:cancel:sender-targeting": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/cancellation#behavior-requirements",
        behavior=(
            "Cancellation notifications reference only requests that were previously issued in the same "
            "direction and are believed to still be in flight."
        ),
        deferred=(
            "Not implemented in the SDK: there is no public client-side cancel API to drive (see "
            "protocol:cancel:abort-signal), so the sender-side targeting rule has nothing to pin."
        ),
    ),
    "protocol:error:connection-closed": Requirement(
        source="sdk",
        behavior="Closing the transport fails all in-flight requests with a connection-closed error.",
    ),
    "protocol:error:internal-error": Requirement(
        source=f"{SPEC_BASE_URL}/basic#responses",
        behavior=(
            "An unhandled exception in a request handler is returned to the caller as JSON-RPC error "
            "-32603 Internal error."
        ),
        divergence=Divergence(
            note=(
                "The low-level Server returns code 0 (not a defined JSON-RPC code) instead of -32603 and "
                "leaks str(exc) as the error message."
            ),
        ),
    ),
    "protocol:error:invalid-params": Requirement(
        source=f"{SPEC_BASE_URL}/basic#responses",
        behavior="A request with malformed params is answered with JSON-RPC error -32602 Invalid params.",
    ),
    "protocol:error:method-not-found": Requirement(
        source=f"{SPEC_BASE_URL}/basic#responses",
        behavior="A request whose method has no registered handler is answered with a METHOD_NOT_FOUND error.",
    ),
    "protocol:meta:related-task": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#related-task-metadata",
        behavior="Messages may carry related-task _meta associating them with a task.",
        deferred=_TASKS_DEFERRAL,
    ),
    "meta:request-to-handler": Requirement(
        source=f"{SPEC_BASE_URL}/basic#_meta",
        behavior="The _meta object the client attaches to a request is visible to the server handler.",
    ),
    "meta:result-to-client": Requirement(
        source=f"{SPEC_BASE_URL}/basic#_meta",
        behavior="The _meta object a handler attaches to its result is delivered to the client.",
    ),
    "protocol:progress:callback": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/progress#progress-flow",
        behavior=(
            "Progress notifications emitted by a handler during a request are delivered to the caller's "
            "progress callback, in order, with their progress, total, and message."
        ),
    ),
    "protocol:progress:token-injected": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/progress#progress-flow",
        behavior=(
            "Supplying a progress callback attaches a progress token to the outgoing request, which the "
            "server-side handler can observe in its request metadata."
        ),
    ),
    "protocol:progress:token-unique": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/progress#progress-flow",
        behavior=("Concurrent in-flight requests that each supply a progress callback carry distinct progress tokens."),
    ),
    "protocol:progress:monotonic": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/progress#progress-flow",
        behavior=(
            "The progress value increases with each notification for a given token, even when the total is unknown."
        ),
        divergence=Divergence(
            note=(
                "The spec MUST is not enforced: progress values are not validated on either side, so a "
                "handler that emits non-increasing values has them forwarded to the callback unchanged."
            ),
        ),
    ),
    "protocol:progress:stops-after-completion": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/progress#behavior-requirements",
        behavior="Progress notifications for a token stop once the associated request completes.",
        divergence=Divergence(
            note=(
                "send_progress_notification does not check whether the token's request has already "
                "completed; the late notification is sent and reaches the client."
            ),
        ),
    ),
    "protocol:progress:late-dropped-by-client": Requirement(
        source="sdk",
        behavior=(
            "A progress notification that arrives after its request has completed is not delivered to the "
            "original progress callback."
        ),
    ),
    "protocol:progress:no-token": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/progress#progress-flow",
        behavior="Without a progress callback the request carries no progress token.",
    ),
    "protocol:progress:client-to-server": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/progress#progress-flow",
        behavior="A progress notification sent by the client is delivered to the server's progress handler.",
    ),
    "protocol:timeout:basic": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#timeouts",
        behavior=(
            "A request that exceeds its read timeout fails with a request-timeout error instead of "
            "waiting forever for the response."
        ),
    ),
    "protocol:timeout:max-total": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#timeouts",
        behavior="A maximum total timeout is enforced even when progress notifications keep arriving.",
        divergence=Divergence(
            note=(
                "There is no maximum-total-timeout option; only the per-request read timeout exists, so the "
                "spec's SHOULD that an overall maximum is always enforced cannot be satisfied."
            ),
        ),
        deferred=(
            "Not implemented in the SDK: there is no maximum-total-timeout option; only the per-request "
            "read timeout exists."
        ),
    ),
    "protocol:timeout:reset-on-progress": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#timeouts",
        behavior="When configured to do so, each progress notification resets the request's read timeout.",
        deferred=(
            "Not implemented in the SDK: progress notifications do not reset the request read timeout and "
            "no option exists to enable that."
        ),
    ),
    "protocol:timeout:sends-cancellation": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#timeouts",
        behavior=(
            "When a request times out, the sender issues notifications/cancelled for that request before "
            "failing the local call."
        ),
        divergence=Divergence(
            note=(
                "The client only raises locally and sends nothing on timeout, so the server keeps running the handler."
            ),
        ),
    ),
    "protocol:timeout:session-survives": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#timeouts",
        behavior="The session continues to serve new requests after an earlier request timed out.",
    ),
    "protocol:timeout:session-default": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#timeouts",
        behavior="A session-level read timeout applies to every request that does not override it.",
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Tools
    # ═══════════════════════════════════════════════════════════════════════════
    "tools:call:content:audio": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#audio-content",
        behavior="A tool result can carry audio content: base64 data with a mimeType.",
    ),
    "tools:call:content:embedded-resource": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#embedded-resources",
        behavior="A tool result can carry an embedded resource with full text or blob contents.",
    ),
    "tools:call:content:image": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#image-content",
        behavior="A tool result can carry image content: base64 data with a mimeType.",
    ),
    "tools:call:content:mixed": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#tool-result",
        behavior="A tool result can carry multiple content blocks of different types; order is preserved.",
    ),
    "tools:call:content:resource-link": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#resource-links",
        behavior="A tool result can carry a resource_link content block referencing a resource by URI.",
    ),
    "tools:call:content:text": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#text-content",
        behavior="tools/call delivers arguments to the tool handler and returns its text content to the caller.",
    ),
    "tools:call:concurrent": Requirement(
        source="sdk",
        behavior=(
            "Multiple tool calls in flight on one session are dispatched concurrently, and each caller "
            "receives the response to its own request."
        ),
    ),
    "tools:call:elicitation-roundtrip": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#user-interaction-model",
        behavior=(
            "A tool handler that issues an elicitation receives the client's result and can embed it in "
            "the tool call result."
        ),
    ),
    "tools:call:is-error": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#error-handling",
        behavior=(
            "A tool execution failure is returned as a result with isError true and the failure described "
            "in content, not as a JSON-RPC error."
        ),
    ),
    "tools:call:is-error-with-content": Requirement(
        source="issue:#348",
        behavior=(
            "A tool can return a hand-built CallToolResult with isError true that carries arbitrary "
            "content (e.g. an image), not just text; the content blocks and the isError flag reach the "
            "caller intact."
        ),
    ),
    "tools:call:logging-mid-execution": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/logging#log-message-notifications",
        behavior=(
            "Log notifications emitted by a tool handler during execution reach the client's logging "
            "callback before the tool result returns."
        ),
    ),
    "tools:call:progress": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/progress#progress-flow",
        behavior=(
            "Progress notifications emitted by a tool handler reach the caller's progress callback before "
            "the tool result returns."
        ),
    ),
    "tools:call:sampling-roundtrip": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#creating-messages",
        behavior=(
            "A tool handler that issues a sampling request receives the client's completion and can embed "
            "it in the tool call result."
        ),
    ),
    "tools:call:structured-content": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#structured-content",
        behavior="A tool result can carry structuredContent alongside content; the client receives both.",
    ),
    "tools:call:structured-content:text-mirror": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#structured-content",
        behavior="A tool returning structured content also returns the serialized JSON as a text content block.",
    ),
    "tools:call:unknown-name": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#error-handling",
        behavior="tools/call for a name the server does not recognise returns a JSON-RPC error.",
    ),
    "tools:capability:declared": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#capabilities",
        behavior="A server with a list_tools handler advertises the tools capability in its initialize result.",
    ),
    "tools:input-schema:json-schema-2020-12": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#tool",
        behavior=(
            "A tool registered with a JSON Schema 2020-12 inputSchema (nested objects, $defs references) "
            "is discoverable and callable."
        ),
    ),
    "tools:input-schema:preserve-additional-properties": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#tool",
        behavior="tools/list preserves inputSchema additionalProperties as registered.",
    ),
    "tools:input-schema:preserve-defs": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#tool",
        behavior="tools/list preserves inputSchema $defs as registered.",
    ),
    "tools:input-schema:preserve-schema-dialect": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#tool",
        behavior="tools/list preserves the inputSchema $schema dialect URI as registered.",
    ),
    "tools:list-changed": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#list-changed-notification",
        behavior=(
            "When the tool set changes, the server sends notifications/tools/list_changed and it reaches "
            "the client's handler."
        ),
    ),
    "tools:list:basic": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#listing-tools",
        behavior="tools/list returns the registered tools with name, description, and inputSchema.",
    ),
    "tools:list:metadata": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#tool",
        behavior=(
            "Optional Tool fields supplied by the server (title, annotations, outputSchema, icons, _meta) "
            "are delivered to the client unchanged."
        ),
    ),
    "tools:list:pagination": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/pagination#response-format",
        behavior=(
            "tools/list supports cursor pagination: the nextCursor returned by a list handler round-trips "
            "back to the handler as an opaque cursor until the listing is exhausted."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Tools: SDK guarantees
    # ═══════════════════════════════════════════════════════════════════════════
    "client:output-schema:skip-on-error": Requirement(
        source="sdk",
        behavior="The client skips structured-content validation when the tool result has isError true.",
    ),
    "client:output-schema:validate": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#output-schema",
        behavior=(
            "A tool result whose structuredContent does not conform to the tool's declared outputSchema "
            "is rejected by the client: the call raises instead of returning the invalid result."
        ),
    ),
    "client:output-schema:missing-structured": Requirement(
        source="sdk",
        behavior="A tool that declares an output schema but returns no structuredContent fails client-side validation.",
    ),
    "client:output-schema:auto-list": Requirement(
        source="sdk",
        behavior=(
            "Calling a tool whose output schema is not yet cached issues an implicit tools/list to "
            "populate the cache; subsequent calls of the same tool do not."
        ),
        divergence=Divergence(
            note=(
                "Design concern rather than spec violation: the implicit request is invisible to the "
                "caller, and against a server that registers only on_call_tool a successful call surfaces "
                "as METHOD_NOT_FOUND from a tools/list the caller never asked for."
            ),
        ),
    ),
    "mcpserver:output-schema:missing-structured": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#output-schema",
        behavior="A tool with an output schema whose function returns no structured content produces a server error.",
    ),
    "mcpserver:output-schema:server-validate": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#output-schema",
        behavior=(
            "MCPServer validates structured content against the tool's output schema before returning; a "
            "mismatch produces a server error."
        ),
    ),
    "mcpserver:output-schema:skip-on-error": Requirement(
        source="sdk",
        behavior="Server-side output schema validation is skipped when the tool returns an isError result.",
    ),
    "mcpserver:tool:duplicate-name": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#tool-names",
        behavior="Registering a tool with a name already in use is rejected at registration time.",
        divergence=Divergence(
            note=(
                "MCPServer logs a warning and keeps the first registration instead of rejecting; "
                "warn_on_duplicate_tools defaults to True and warning is the only effect -- there is "
                "no rejection mode."
            ),
        ),
    ),
    "mcpserver:tool:extra": Requirement(
        source="sdk",
        behavior=(
            "Tool functions can access request metadata (request id, client params, session) through the "
            "Context parameter."
        ),
    ),
    "mcpserver:tool:handler-throws": Requirement(
        source="sdk",
        behavior=(
            "An exception raised by a tool function (ToolError or otherwise) is caught and returned as a "
            "tool result with isError true and the failure text in content; it does not become a JSON-RPC error."
        ),
    ),
    "mcpserver:tool:input-validation": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#error-handling",
        behavior=(
            "Arguments that fail the tool's input validation produce a tool execution error (isError true "
            "with the validation failure described in content) without invoking the function."
        ),
    ),
    "mcpserver:tool:naming-validation": Requirement(
        source="sdk",
        behavior=(
            "Registering a tool whose name violates the spec's tool-naming conventions emits a warning; "
            "registration still succeeds."
        ),
    ),
    "mcpserver:tool:output-schema:model": Requirement(
        source="sdk",
        behavior=(
            "A tool returning a typed model advertises a matching generated outputSchema and returns the "
            "model's fields as structuredContent alongside a serialised text block."
        ),
    ),
    "mcpserver:tool:output-schema:wrapped": Requirement(
        source="sdk",
        behavior=(
            "A tool returning a non-object type (primitive or list) wraps the value as {'result': ...} in "
            "structuredContent, with a matching generated outputSchema."
        ),
    ),
    "mcpserver:tool:schema-variants": Requirement(
        source="sdk",
        behavior=(
            "Tool input schemas generated from complex parameter types (unions, nested models, "
            "constrained types) validate and coerce arguments before the function runs."
        ),
    ),
    "mcpserver:tool:unknown-name": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#error-handling",
        behavior="tools/call for a name that was never registered returns a JSON-RPC error.",
        divergence=Divergence(
            note=(
                "The spec classifies unknown tools as a protocol error (its example uses -32602 Invalid "
                "params); MCPServer reports a tool execution error (isError true) instead. The low-level "
                "path follows the spec example (see tools:call:unknown-name)."
            ),
        ),
    ),
    "mcpserver:tool:url-elicitation-error": Requirement(
        source="sdk",
        behavior=(
            "A tool function that raises the URL-elicitation-required error surfaces to the caller as "
            "error -32042 with the elicitation parameters intact."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # MCPServer: Context helpers (SDK)
    # ═══════════════════════════════════════════════════════════════════════════
    "mcpserver:context:logging": Requirement(
        source="sdk",
        behavior=(
            "The Context logging helpers (debug/info/warning/error) send log message notifications at the "
            "corresponding severity."
        ),
    ),
    "mcpserver:context:progress": Requirement(
        source="sdk",
        behavior=(
            "Context.report_progress sends a progress notification against the requesting client's progress token."
        ),
    ),
    "mcpserver:context:elicit": Requirement(
        source="sdk",
        behavior=(
            "Context.elicit sends a form elicitation built from a typed schema and returns a typed "
            "accepted/declined/cancelled result."
        ),
    ),
    "mcpserver:context:read-resource": Requirement(
        source="sdk",
        behavior="Context.read_resource reads a resource registered on the same server from inside a tool.",
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Resources
    # ═══════════════════════════════════════════════════════════════════════════
    "resources:annotations": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#annotations",
        behavior="Resource annotations supplied by the server round-trip to the client in the list result.",
        divergence=Divergence(
            note=(
                "The SDK Annotations model is missing the schema's lastModified field; MCPModel uses the "
                "pydantic default extra='ignore', so the value is silently dropped on parse."
            ),
        ),
    ),
    "resources:capability:declared": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#capabilities",
        behavior=(
            "A server with resource handlers advertises the resources capability, including the subscribe "
            "sub-flag when a subscribe handler is registered."
        ),
    ),
    "resources:list-changed": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#list-changed-notification",
        behavior=(
            "When the resource set changes, the server sends notifications/resources/list_changed and it "
            "reaches the client's handler."
        ),
    ),
    "resources:list:basic": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#listing-resources",
        behavior=(
            "resources/list returns the registered resources with uri, name, and the optional descriptive "
            "fields supplied by the server."
        ),
    ),
    "resources:list:pagination": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/pagination#operations-supporting-pagination",
        behavior="resources/list supports cursor pagination.",
    ),
    "resources:read:blob": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#reading-resources",
        behavior="resources/read returns binary contents base64-encoded in blob.",
    ),
    "resources:read:template-vars": Requirement(
        source="sdk",
        behavior="Variables extracted from a templated resource URI reach the resource function as typed arguments.",
    ),
    "resources:read:text": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#reading-resources",
        behavior="resources/read returns text contents carrying uri, mimeType, and the text.",
    ),
    "resources:read:unknown-uri": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#error-handling",
        behavior="resources/read for an unknown URI returns JSON-RPC error -32002 (resource not found).",
    ),
    "resources:subscribe": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#subscriptions",
        behavior="resources/subscribe delivers the URI to the server's subscribe handler and returns an empty result.",
    ),
    "resources:subscribe:capability-required": Requirement(
        source="sdk",
        behavior=(
            "resources/subscribe to a server that did not advertise the subscribe capability is rejected with an error."
        ),
    ),
    "resources:subscribe:updated": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#subscriptions",
        behavior="After resources/subscribe, changes to that resource send notifications/resources/updated.",
        deferred=(
            "Not implemented in the SDK: the server keeps no subscription state linking subscribe to "
            "updated notifications; emitting updates is entirely handler code. The two halves are pinned "
            "separately by resources:subscribe and resources:updated-notification."
        ),
    ),
    "resources:templates:list": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#resource-templates",
        behavior=(
            "resources/templates/list returns the registered templates with their uriTemplate and descriptive fields."
        ),
    ),
    "resources:templates:pagination": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/pagination#operations-supporting-pagination",
        behavior="resources/templates/list supports cursor pagination.",
    ),
    "resources:unsubscribe": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#subscriptions",
        behavior=(
            "resources/unsubscribe delivers the URI to the server's unsubscribe handler and returns an empty result."
        ),
    ),
    "resources:unsubscribe:stops-updates": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#subscriptions",
        behavior="After resources/unsubscribe the server stops sending updated notifications for that URI.",
        deferred=(
            "Not implemented in the SDK: the server keeps no subscription state, so whether updated "
            "notifications stop after unsubscribe is entirely handler code; there is no SDK behaviour to "
            "pin beyond the unsubscribe request reaching the handler (covered by resources:unsubscribe)."
        ),
    ),
    "resources:updated-notification": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#subscriptions",
        behavior=(
            "A resources/updated notification sent by the server reaches the client carrying the URI of "
            "the changed resource."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Resources: SDK guarantees
    # ═══════════════════════════════════════════════════════════════════════════
    "mcpserver:resource:duplicate-name": Requirement(
        source="sdk",
        behavior="Registering a resource or template with a duplicate identifier is rejected at registration time.",
        divergence=Divergence(
            note=(
                "MCPServer logs a warning and keeps the first registration instead of rejecting; same "
                "warn-and-ignore behaviour as duplicate tool names (mcpserver:tool:duplicate-name). "
                "Templates differ: a duplicate uri_template silently replaces the first with no warning."
            ),
        ),
    ),
    "mcpserver:resource:read-throws-surfaced": Requirement(
        source="sdk",
        behavior="A resource function that raises is surfaced to the caller as a JSON-RPC error response.",
    ),
    "mcpserver:resource:static": Requirement(
        source="sdk",
        behavior=(
            "A function registered with @mcp.resource() for a fixed URI is listed by resources/list and "
            "served by resources/read at that URI."
        ),
    ),
    "mcpserver:resource:template": Requirement(
        source="sdk",
        behavior=(
            "A function registered with a URI template is listed by resources/templates/list and matched "
            "by resources/read, receiving the parameters extracted from the requested URI."
        ),
    ),
    "mcpserver:resource:unknown-uri": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#error-handling",
        behavior="resources/read for a URI matching no registered resource returns JSON-RPC error -32002.",
        divergence=Divergence(
            note=(
                "The spec reserves -32002 for resource-not-found; MCPServer raises ResourceError, which "
                "the low-level server converts to error code 0."
            ),
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Prompts
    # ═══════════════════════════════════════════════════════════════════════════
    "prompts:capability:declared": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#capabilities",
        behavior="A server with a list_prompts handler advertises the prompts capability in its initialize result.",
    ),
    "prompts:get:content:audio": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#audio-content",
        behavior="Prompt messages may contain audio content with base64 data and a mimeType.",
    ),
    "prompts:get:content:embedded-resource": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#embedded-resources",
        behavior="Prompt messages may contain embedded resource content.",
    ),
    "prompts:get:content:image": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#image-content",
        behavior="Prompt messages may contain image content.",
    ),
    "prompts:get:missing-required-args": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#error-handling",
        behavior="prompts/get omitting a required argument returns JSON-RPC error -32602 (Invalid params).",
        divergence=Divergence(
            note=(
                "MCPServer's prompt renderer raises a plain ValueError before the prompt function runs, "
                "which the low-level server converts to error code 0 with the exception text as the message."
            ),
        ),
    ),
    "prompts:get:multi-message": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#getting-a-prompt",
        behavior="A prompt can return multiple messages mixing user and assistant roles; order is preserved.",
    ),
    "prompts:get:no-args": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#getting-a-prompt",
        behavior="prompts/get with no arguments returns the prompt's messages.",
    ),
    "prompts:get:unknown-name": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#error-handling",
        behavior="prompts/get for an unknown prompt name returns JSON-RPC error -32602 (Invalid params).",
    ),
    "prompts:get:with-args": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#getting-a-prompt",
        behavior="prompts/get delivers the supplied arguments to the prompt handler and returns its messages.",
    ),
    "prompts:list-changed": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#list-changed-notification",
        behavior=(
            "When the prompt set changes, the server sends notifications/prompts/list_changed and it "
            "reaches the client's handler."
        ),
    ),
    "prompts:list:basic": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#listing-prompts",
        behavior="prompts/list returns the registered prompts with name, description, and argument declarations.",
    ),
    "prompts:list:pagination": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/pagination#operations-supporting-pagination",
        behavior="prompts/list supports cursor pagination.",
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Prompts: SDK guarantees
    # ═══════════════════════════════════════════════════════════════════════════
    "mcpserver:prompt:args-validation": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#implementation-considerations",
        behavior="prompts/get arguments that fail the prompt's argument schema are rejected before the function runs.",
    ),
    "mcpserver:prompt:decorated": Requirement(
        source="sdk",
        behavior=(
            "A function registered with @mcp.prompt() is listed with arguments derived from its signature "
            "and rendered into prompt messages by prompts/get."
        ),
    ),
    "mcpserver:prompt:duplicate-name": Requirement(
        source="sdk",
        behavior="Registering a duplicate prompt name is rejected at registration time.",
        divergence=Divergence(
            note=(
                "MCPServer logs a warning and keeps the first registration instead of rejecting; same "
                "warn-and-ignore behaviour as duplicate tool names (mcpserver:tool:duplicate-name)."
            ),
        ),
    ),
    "mcpserver:prompt:optional-args": Requirement(
        source="sdk",
        behavior="A prompt with optional arguments can be fetched without supplying them.",
    ),
    "mcpserver:prompt:unknown-name": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#error-handling",
        behavior="prompts/get for a name that was never registered returns JSON-RPC error -32602 (Invalid params).",
        divergence=Divergence(
            note=(
                "The spec's example uses -32602 Invalid params for unknown prompts; MCPServer raises "
                "ValueError, which the low-level server converts to error code 0."
            ),
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Completion
    # ═══════════════════════════════════════════════════════════════════════════
    "completion:capability:declared": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/completion#capabilities",
        behavior="A server with a completion handler advertises the completions capability in its initialize result.",
    ),
    "completion:complete:not-supported": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/completion#capabilities",
        behavior=(
            "A server with no completion handler does not advertise the completions capability and rejects "
            "completion/complete with METHOD_NOT_FOUND."
        ),
    ),
    "completion:context-arguments": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/completion#requesting-completions",
        behavior="Previously-resolved argument values supplied in context.arguments reach the completion handler.",
    ),
    "completion:error:invalid-ref": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/completion#error-handling",
        behavior=(
            "completion/complete with a ref naming an unknown prompt or non-matching resource URI returns "
            "JSON-RPC error -32602 (Invalid params)."
        ),
    ),
    "completion:prompt-arg": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/completion#reference-types",
        behavior="completion/complete with a ref/prompt returns suggested values for the named prompt argument.",
    ),
    "completion:resource-template-arg": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/completion#reference-types",
        behavior="completion/complete with a ref/resource returns suggested values for a URI template variable.",
    ),
    "completion:result-shape": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/completion#completion-results",
        behavior="The completion result carries values (at most 100), an optional total, and an optional hasMore flag.",
    ),
    "mcpserver:completion:capability-auto": Requirement(
        source="sdk",
        behavior=(
            "MCPServer advertises the completions capability when at least one completion source is "
            "registered, and omits it otherwise."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Logging
    # ═══════════════════════════════════════════════════════════════════════════
    "logging:capability:declared": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/logging#capabilities",
        behavior=(
            "A server that emits log message notifications declares the logging capability in its initialize result."
        ),
        divergence=Divergence(
            note=(
                "MCPServer registers no setLevel handler, so capability derivation leaves logging unset "
                "even though the Context helpers send log message notifications."
            ),
        ),
    ),
    "logging:message:all-levels": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/logging#log-levels",
        behavior="All eight RFC 5424 severity levels are deliverable as log message notifications.",
    ),
    "logging:message:fields": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/logging#log-message-notifications",
        behavior=(
            "A log message sent by a server handler is delivered to the client's logging callback with its "
            "severity level, logger name, and data."
        ),
    ),
    "logging:message:filtered": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/logging#setting-log-level",
        behavior="After logging/setLevel, log messages below the configured level are not sent.",
        divergence=Divergence(
            note=(
                "Neither MCPServer (which rejects logging/setLevel with method-not-found) nor the "
                "low-level Server (which leaves the handler entirely to the author) implements any "
                "filtering; messages are delivered at every severity regardless of the requested level."
            ),
        ),
    ),
    "logging:set-level": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/logging#setting-log-level",
        behavior="logging/setLevel delivers the requested level to the server's handler and returns an empty result.",
    ),
    "logging:set-level:invalid-level": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/logging#error-handling",
        behavior="logging/setLevel with an invalid level value returns JSON-RPC error -32602 (Invalid params).",
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Sampling (server → client)
    # ═══════════════════════════════════════════════════════════════════════════
    "sampling:capability:declare": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#capabilities",
        behavior=(
            "A client that handles sampling requests advertises the sampling capability in its initialize request."
        ),
    ),
    "sampling:create:basic": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#creating-messages",
        behavior=(
            "A sampling/createMessage request from a server handler is answered by the client's sampling "
            "callback, and the callback's result (role, content, model, stopReason) is returned to the handler."
        ),
    ),
    "sampling:create:include-context": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#capabilities",
        behavior="The includeContext value supplied by the server reaches the client callback intact.",
    ),
    "sampling:context:server-gated-by-capability": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#capabilities",
        behavior=(
            "The server does not use includeContext values thisServer or allServers unless the client "
            "declared the sampling.context capability."
        ),
        divergence=Divergence(
            note=(
                "include_context is forwarded regardless of the client's declared sampling.context "
                "capability; the server-side validator only checks tools/tool_choice."
            ),
        ),
    ),
    "sampling:create:model-preferences": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#model-preferences",
        behavior=(
            "The model preferences supplied by the server (hints and the cost, speed, and intelligence "
            "priorities) reach the client callback intact."
        ),
    ),
    "sampling:create:system-prompt": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#creating-messages",
        behavior="The system prompt supplied by the server reaches the client callback intact.",
    ),
    "sampling:create:tools": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#tools-in-sampling",
        behavior=(
            "A sampling request carrying tools and toolChoice reaches the client, and a tool_use response "
            "with a toolUse stop reason returns to the requesting handler."
        ),
        deferred=(
            "Not implemented in the SDK: Client does not expose ClientSession's sampling_capabilities "
            "parameter, so a client can never declare sampling.tools and the server-side validator "
            "rejects every tool-enabled request before it is sent."
        ),
    ),
    "sampling:create-message:audio-content": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#audio-content",
        behavior="Sampling messages can carry audio content: base64 data with a mimeType.",
    ),
    "sampling:create-message:image-content": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#image-content",
        behavior="Sampling messages can carry image content: base64 data with a mimeType.",
    ),
    "sampling:create-message:not-supported": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#capabilities",
        behavior=(
            "A sampling request to a client that did not declare the sampling capability fails with an "
            "error rather than hanging or being silently dropped; the spec names no error code for this case."
        ),
    ),
    "sampling:error:user-rejected": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#error-handling",
        behavior=(
            "A sampling request the user rejects is answered with a JSON-RPC error (the spec's code for "
            "this case is -1, 'User rejected sampling request'), surfaced to the requesting handler as an MCPError."
        ),
    ),
    "sampling:message:content-cardinality": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling",
        behavior="A sampling message's content may be a single block or an array of blocks.",
    ),
    "sampling:result:no-tools-single-content": Requirement(
        source="sdk",
        behavior=(
            "When the request carries no tools, a sampling callback result whose content is an array is "
            "rejected by the client."
        ),
        divergence=Divergence(
            note=(
                "The client does not validate the callback result against the request shape; an array-content "
                "result for a tool-free request is accepted client-side and surfaces as a raw "
                "pydantic.ValidationError from the server's response parsing (send_request) instead."
            ),
        ),
    ),
    "sampling:result:with-tools-array-content": Requirement(
        source="sdk",
        behavior=(
            "When the request includes tools, the client accepts a callback result whose content is an "
            "array including tool_use blocks."
        ),
        deferred=(
            "Not implemented in the SDK: requires declaring sampling.tools, which the high-level client "
            "cannot do (see sampling:create:tools)."
        ),
    ),
    "sampling:tool-result:no-mixed-content": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#tool-result-messages",
        behavior=(
            "A user sampling message that carries tool_result content contains only tool_result blocks; "
            "mixing tool_result with text, image, or audio content is rejected as invalid."
        ),
    ),
    "sampling:tool-use:result-balance": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#tool-use-and-result-balance",
        behavior=(
            "In a sampling/createMessage request, every assistant tool_use block in messages MUST be "
            "matched by a tool_result with the same toolUseId in the immediately-following user message; "
            "an unmatched tool_use is rejected with -32602 Invalid params."
        ),
        divergence=Divergence(
            note=(
                "The client does not validate inbound tool_use/tool_result balance; the SDK enforces "
                "the rule server-side instead, before the request leaves the server (see "
                "sampling:tool-use:server-preflight)."
            ),
        ),
        deferred=(
            "Not implemented on the client receive path: validation runs only on the server send path "
            "(pinned by sampling:tool-use:server-preflight)."
        ),
    ),
    "sampling:tool-use:server-preflight": Requirement(
        source="sdk",
        behavior=(
            "The server validates tool_use/tool_result balance before sending a sampling/createMessage "
            "request; an unmatched tool_use raises ValueError and the request never reaches the wire."
        ),
    ),
    "sampling:tools:server-gated-by-capability": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#tools-in-sampling",
        behavior=(
            "A tool-enabled sampling request to a client that did not declare sampling.tools is rejected "
            "by the server before anything reaches the wire (the SDK surfaces this as an Invalid params error)."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Elicitation (server → client)
    # ═══════════════════════════════════════════════════════════════════════════
    "elicitation:capability:empty-is-form": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#capabilities",
        behavior="A client advertising an empty elicitation capability accepts form-mode elicitation requests.",
        deferred=(
            "Not implemented in the SDK: a Client with an elicitation callback always declares explicit "
            "form and url sub-capabilities, so an empty elicitation capability cannot be produced through "
            "the public API."
        ),
    ),
    "elicitation:capability:mode-mismatch": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#error-handling",
        behavior=(
            "The client answers elicitation requests for a mode it did not advertise with JSON-RPC error "
            "-32602 (Invalid params)."
        ),
        deferred=(
            "Not implemented in the SDK: a client cannot be configured form-only or url-only, so the "
            "per-mode mismatch error cannot arise (see elicitation:url:not-supported)."
        ),
    ),
    "elicitation:capability:server-respects-mode": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#capabilities",
        behavior=(
            "The server refuses to send an elicitation request with a mode the connected client did not "
            "declare in its capabilities."
        ),
        divergence=Divergence(
            note=(
                "The server does not check the client's declared elicitation modes before sending "
                "elicitation/create; the spec's MUST NOT is not enforced."
            ),
        ),
    ),
    "elicitation:form:action:accept": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#response-actions",
        behavior=(
            "A form-mode elicitation answered with action 'accept' returns the user's content to the "
            "requesting handler."
        ),
    ),
    "elicitation:form:action:cancel": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#response-actions",
        behavior="A form-mode elicitation answered with action 'cancel' returns no content to the handler.",
    ),
    "elicitation:form:action:decline": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#response-actions",
        behavior="A form-mode elicitation answered with action 'decline' returns no content to the handler.",
    ),
    "elicitation:form:basic": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#form-mode-elicitation-requests",
        behavior=(
            "A form-mode elicitation delivers the message and requested schema to the client callback "
            "exactly as the server sent them."
        ),
    ),
    "elicitation:form:defaults": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#requested-schema",
        behavior=(
            "Optional default values declared in a form-mode requested schema are pre-populated into the "
            "form presented to the user."
        ),
        deferred=(
            "Not implemented in the SDK: there is no form-rendering layer that could pre-populate "
            "defaults; client callbacks receive the requested schema as-is."
        ),
    ),
    "elicitation:form:mode-omitted-default": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#elicitation-requests",
        behavior="An elicitation request with no mode field is treated as form mode by the client.",
    ),
    "elicitation:form:not-supported": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#error-handling",
        behavior=(
            "An elicitation request to a client that did not declare the elicitation capability is "
            "answered with -32602 Invalid params."
        ),
        divergence=Divergence(
            note="The client's default callback answers with -32600 Invalid request instead of -32602.",
        ),
    ),
    "elicitation:form:schema:enum-variants": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#requested-schema",
        behavior=(
            "Requested-schema enum fields (including titled and multi-select variants) reach the client "
            "callback as sent."
        ),
    ),
    "elicitation:form:schema:primitives": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#requested-schema",
        behavior="Requested-schema fields may be string (with format), number or integer, or boolean.",
    ),
    "elicitation:form:schema:restricted-subset": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#requested-schema",
        behavior=(
            "Form-mode requested schemas are flat objects with primitive-typed properties only; nested "
            "structures and arrays of objects are not used."
        ),
        divergence=Divergence(
            note=(
                "ServerSession.elicit_form forwards an arbitrary dict[str, Any] schema unchanged; no shape "
                "validation at the low-level session layer (the high-level Context.elicit / "
                "elicit_with_validation helper enforces primitive-only fields before generating the schema)."
            ),
        ),
    ),
    "elicitation:form:response-validation": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#form-mode-security",
        behavior=(
            "Accepted form-mode content is validated against the requested schema: the client validates "
            "the response before sending and the server validates the content it receives."
        ),
        divergence=Divergence(
            note=(
                "The client never validates outbound content; ServerSession.elicit_form returns received "
                "content unvalidated (the high-level Context.elicit / elicit_with_validation helper "
                "validates server-side, but the low-level session API does not)."
            ),
        ),
    ),
    "elicitation:url:action:accept-no-content": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#response-actions",
        behavior=(
            "A URL-mode elicitation delivers the message, URL, and elicitationId to the client; an accept "
            "response carries no content (accept means the user agreed to visit the URL, not that the "
            "interaction completed)."
        ),
    ),
    "elicitation:url:basic": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#url-mode-elicitation-requests",
        behavior=(
            "A url-mode elicitation delivers the elicitation id and URL to the client callback exactly as "
            "the server sent them."
        ),
    ),
    "elicitation:url:cancel": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#response-actions",
        behavior="A URL-mode elicitation answered with cancel returns the action with no content.",
    ),
    "elicitation:url:complete-notification": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#completion-notifications-for-url-mode-elicitation",
        behavior=(
            "An elicitation/complete notification sent by the server after an out-of-band elicitation "
            "finishes reaches the client carrying the elicitationId."
        ),
    ),
    "elicitation:url:complete-unknown-ignored": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#completion-notifications-for-url-mode-elicitation",
        behavior=(
            "The client ignores an elicitation/complete notification referencing an unknown or "
            "already-completed elicitationId without error."
        ),
    ),
    "elicitation:url:decline": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#response-actions",
        behavior="A URL-mode elicitation answered with decline returns the action with no content.",
    ),
    "elicitation:url:not-supported": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#error-handling",
        behavior=(
            "A URL-mode elicitation to a client that declared only form-mode support is rejected with an "
            "Invalid params error."
        ),
        deferred=(
            "Not implemented in the SDK: a Client with an elicitation callback always declares both the "
            "form and url sub-capabilities, so a form-only client cannot be constructed."
        ),
    ),
    "elicitation:url:required-error": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#url-elicitation-required-error",
        behavior=(
            "A handler that cannot proceed without a URL elicitation rejects the request with error "
            "-32042, carrying the pending elicitations in the error data."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Roots (server → client)
    # ═══════════════════════════════════════════════════════════════════════════
    "roots:list-changed": Requirement(
        source=f"{SPEC_BASE_URL}/client/roots#root-list-changes",
        behavior="A roots/list_changed notification sent by the client is delivered to the server's handler.",
    ),
    "roots:list-changed:client-emits": Requirement(
        source=f"{SPEC_BASE_URL}/client/roots#root-list-changes",
        behavior=(
            "A client that declared roots.listChanged sends notifications/roots/list_changed when its set "
            "of roots changes."
        ),
        deferred=(
            "Not implemented in the SDK: the client does not own the root set (it calls back to the host "
            "via list_roots_callback), so there is no mutation it could observe to auto-emit on; the SDK "
            "provides send_roots_list_changed() for the host to call when its roots change, and that "
            "emission path is covered by roots:list-changed."
        ),
    ),
    "roots:list:basic": Requirement(
        source=f"{SPEC_BASE_URL}/client/roots#listing-roots",
        behavior=(
            "A roots/list request from a server handler is answered by the client's roots callback, and "
            "the returned roots (uri, name) reach the handler."
        ),
    ),
    "roots:list:client-error": Requirement(
        source=f"{SPEC_BASE_URL}/client/roots#error-handling",
        behavior="A roots callback that answers with an error surfaces to the requesting handler as an MCPError.",
    ),
    "roots:list:empty": Requirement(
        source=f"{SPEC_BASE_URL}/client/roots#listing-roots",
        behavior="An empty roots list is a valid response and reaches the handler as such.",
    ),
    "roots:list:not-supported": Requirement(
        source=f"{SPEC_BASE_URL}/client/roots#error-handling",
        behavior=(
            "A roots/list request to a client that did not declare the roots capability is answered with "
            "-32601 Method not found."
        ),
        divergence=Divergence(
            note="The client's default callback answers with -32600 Invalid request instead of -32601.",
        ),
    ),
    "roots:uri:file-scheme": Requirement(
        source=f"{SPEC_BASE_URL}/client/roots#root",
        behavior="Every root returned by the client identifies itself with a file:// URI.",
        deferred=(
            "Schema-level validation: the FileUrl type on Root.uri rejects any non-file:// scheme at "
            "construction and at parse, so a non-conforming root cannot reach the wire from either side; "
            "type-level coverage belongs in tests/test_types.py rather than this interaction suite."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # list_changed & dynamic registration
    # ═══════════════════════════════════════════════════════════════════════════
    "client:list-changed:auto-refresh": Requirement(
        source="sdk",
        behavior=(
            "A client configured to react to list_changed notifications automatically re-fetches the "
            "corresponding list and delivers the fresh result to its callback."
        ),
        deferred=(
            "Not implemented in the SDK: the client has no list-changed auto-refresh mechanism; "
            "notifications are only delivered to the message handler."
        ),
    ),
    "client:list-changed:capability-gated": Requirement(
        source="sdk",
        behavior=(
            "The client does not activate list-changed handling for a kind the server did not advertise "
            "with listChanged true."
        ),
        deferred="Not implemented in the SDK: no client-side list-changed handling exists to gate.",
    ),
    "client:list-changed:signal-only": Requirement(
        source="sdk",
        behavior="A client configured for signal-only list-changed handling is notified without auto-refreshing.",
        deferred="Not implemented in the SDK: no client-side list-changed handling exists.",
    ),
    "mcpserver:list-changed:debounce": Requirement(
        source="sdk",
        behavior=(
            "Bursts of registration changes on MCPServer are debounced into one list_changed notification per kind."
        ),
        deferred=(
            "Not implemented in the SDK: MCPServer does not send list_changed notifications on "
            "registration changes at all (see mcpserver:register:post-connect), so there is nothing to "
            "debounce."
        ),
    ),
    "mcpserver:register:post-connect": Requirement(
        source="sdk",
        behavior=(
            "A tool, resource, or prompt registered or removed after the client connected appears in (or "
            "disappears from) the corresponding list results, and the change is announced with a "
            "list_changed notification."
        ),
        divergence=Divergence(
            note=(
                "MCPServer never sends list_changed notifications on registration changes, so a connected "
                "client cannot learn that the set changed without polling."
            ),
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Pagination
    # ═══════════════════════════════════════════════════════════════════════════
    "pagination:exhaustion": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/pagination#response-format",
        behavior=(
            "Following nextCursor until it is absent yields every page exactly once; a result without "
            "nextCursor ends the sequence."
        ),
    ),
    "pagination:invalid-cursor": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/pagination#error-handling",
        behavior="A list request with an invalid cursor returns JSON-RPC error -32602 (Invalid params).",
    ),
    "pagination:client:cursor-handling": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/pagination#implementation-guidelines",
        behavior=(
            "The client treats cursors as opaque tokens — it does not parse, modify, or persist them — "
            "and does not assume a fixed page size."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Tasks (experimental)
    # ═══════════════════════════════════════════════════════════════════════════
    "tasks:auth:context-isolation": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#task-isolation-and-access-control",
        behavior=(
            "When an authorization context is available, task operations are scoped to the context that "
            "created the task: other contexts cannot get it, retrieve its result, cancel it, or see it in "
            "tasks/list."
        ),
        transports=("streamable-http",),
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:bidirectional": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#definitions",
        behavior="Task APIs are bidirectional: the server may create, get, list, and cancel tasks on the client.",
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:cancel:no-handler-abort": Requirement(
        source="sdk",
        behavior=(
            "tasks/cancel marks the task cancelled without aborting the originating request handler "
            "(the spec says receivers SHOULD attempt to stop execution)."
        ),
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:cancel:remains-cancelled": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#task-cancellation",
        behavior=(
            "After tasks/cancel, the task remains cancelled even if the underlying handler subsequently "
            "completes or fails."
        ),
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:cancel:terminal-rejected": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#task-cancellation",
        behavior="tasks/cancel on a task already in a terminal state returns Invalid params (-32602).",
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:cancel:working": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#task-cancellation",
        behavior="tasks/cancel on a working task transitions it to cancelled and returns the updated task.",
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:create:ttl-honored": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#ttl-and-resource-management",
        behavior=(
            "tasks/get responses include the actual ttl applied by the receiver (or null for unlimited); "
            "the create-task result carries the same value."
        ),
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:create:via-tool-call": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#creating-tasks",
        behavior="A task-augmented tools/call returns a create-task result instead of the tool result.",
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:get": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#getting-tasks",
        behavior="tasks/get returns the task's current status, ttl, timestamps, and status message.",
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:lifecycle:initial-working": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#task-status-lifecycle",
        behavior="A newly created task has status 'working'.",
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:lifecycle:input-required": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#input-required-status",
        behavior=(
            "While a task awaits a side-channel client response its status is input_required; once the "
            "response arrives the task leaves input_required (typically returning to working)."
        ),
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:list:invalid-cursor": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#protocol-errors",
        behavior="tasks/list with an invalid cursor returns Invalid params (-32602).",
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:list:pagination": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#listing-tasks",
        behavior="tasks/list returns created tasks and supports cursor pagination.",
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:no-capability:ignore-task-param": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#task-support-and-handling",
        behavior=(
            "A receiver that did not declare task capability for a request type processes the request "
            "normally and returns the ordinary result, ignoring the task augmentation."
        ),
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:progress:after-create": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#task-progress-notifications",
        behavior=(
            "After the create-task result, progress notifications keyed to the original progress token "
            "continue to reach the caller until the task is terminal."
        ),
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:request-cancel:no-task-cancel": Requirement(
        source="sdk",
        behavior="A cancellation notification for the originating request does not auto-cancel the created task.",
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:result:failed": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#task-execution-errors",
        behavior="tasks/result for a failed task returns the failure result (isError true).",
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:result:related-task-meta": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#related-task-metadata",
        behavior="The tasks/result response carries related-task _meta naming the requested task.",
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:result:terminal": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#result-retrieval",
        behavior="tasks/result for a completed task returns the stored result of the original request type.",
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:side-channel:drain-fifo": Requirement(
        source="sdk",
        behavior="tasks/result drains queued related-task messages in FIFO order before returning the final result.",
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:side-channel:drop-on-cancel": Requirement(
        source="sdk",
        behavior="When a task is cancelled before tasks/result, queued related-task messages are dropped.",
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:side-channel:elicitation": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#input-required-status",
        behavior=(
            "An elicitation issued mid-task is delivered through the tasks/result side-channel, and the "
            "client's response routes back to the handler."
        ),
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:side-channel:queue": Requirement(
        source="sdk",
        behavior=(
            "Server-to-client requests with related-task metadata sent while no tasks/result is open are queued."
        ),
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:side-channel:sampling": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#input-required-status",
        behavior=(
            "A sampling request issued mid-task is delivered through the tasks/result side-channel, and "
            "the client's response routes back to the task."
        ),
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:side-channel:stream": Requirement(
        source="sdk",
        behavior=(
            "Calling tasks/result while the task is working streams related-task messages as they are "
            "produced, then returns the result."
        ),
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:status-notification": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#task-status-notification",
        behavior="Task status notifications deliver status updates carrying the full task fields.",
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:tool-level:forbidden-with-task-32601": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#tool-level-negotiation",
        behavior=(
            "A task-augmented tools/call on a tool that does not support tasks returns Method not found (-32601)."
        ),
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:tool-level:required-no-task-32601": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#tool-level-negotiation",
        behavior=("A plain tools/call on a tool that requires task augmentation returns Method not found (-32601)."),
        deferred=_TASKS_DEFERRAL,
    ),
    "tasks:unknown-id": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#protocol-errors",
        behavior="tasks/get, tasks/result, and tasks/cancel for an unknown task id return Invalid params (-32602).",
        deferred=_TASKS_DEFERRAL,
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Transports (in-suite coverage)
    # ═══════════════════════════════════════════════════════════════════════════
    "transport:streamable-http:stateful": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#streamable-http",
        behavior=(
            "The interaction round trip (initialize, tool calls, tool errors) works through the "
            "streamable HTTP framing in its default stateful SSE-response mode."
        ),
        transports=("streamable-http",),
    ),
    "transport:streamable-http:json-response": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#streamable-http",
        behavior="The interaction round trip works when the server answers with plain JSON instead of SSE.",
        transports=("streamable-http",),
    ),
    "transport:streamable-http:stateless": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#streamable-http",
        behavior=(
            "The interaction round trip works in stateless mode, where every request is served by a "
            "fresh transport with no session id."
        ),
        transports=("streamable-http",),
    ),
    "transport:streamable-http:notifications": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#streamable-http",
        behavior=(
            "Notifications emitted during a request are delivered on that request's SSE stream and reach "
            "the client's callbacks, in order, before the response."
        ),
        transports=("streamable-http",),
    ),
    "transport:streamable-http:stateless-restrictions": Requirement(
        source="sdk",
        behavior=(
            "A handler that attempts a server-initiated request in stateless mode fails with an error "
            "result, because there is no session to call back through."
        ),
        transports=("streamable-http",),
    ),
    "transport:streamable-http:unrelated-messages": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#streamable-http",
        behavior=(
            "A server-to-client message that is not related to an in-flight request is routed to the "
            "standalone GET stream and delivered to the client listening on it, not to any request's "
            "own stream."
        ),
        transports=("streamable-http",),
    ),
    "transport:streamable-http:server-to-client": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#streamable-http",
        behavior=(
            "A server-initiated request nested inside an in-flight call round-trips over stateful streamable HTTP."
        ),
        transports=("streamable-http",),
    ),
    "transport:streamable-http:resumability": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#streamable-http",
        behavior="A client that reconnects with Last-Event-ID receives the events it missed.",
        transports=("streamable-http",),
    ),
    "transport:streamable-http:origin-validation": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#security-warning",
        behavior="Requests with an invalid Origin header are rejected with 403 before reaching the session.",
        transports=("streamable-http",),
    ),
    "transport:sse": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#backwards-compatibility",
        behavior=(
            "A client connected over the legacy HTTP+SSE transport completes the handshake and round-trips "
            "requests, with server messages delivered on the SSE stream."
        ),
        transports=("sse",),
    ),
    "transport:sse:endpoint-event": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#backwards-compatibility",
        behavior="Opening the SSE stream delivers an `endpoint` event naming the message-POST URL as the first event.",
        transports=("sse",),
    ),
    "transport:sse:post:session-routing": Requirement(
        source="sdk",
        behavior=(
            "The endpoint URL carries a fresh session identifier; the server registers the session before "
            "the endpoint event is sent and releases it when the stream disconnects, and a POST that names "
            "no session id, a malformed session id, or an unknown session id is rejected (400/400/404)."
        ),
        transports=("sse",),
    ),
    "transport:stdio": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#stdio",
        behavior=(
            "A Client connected to a real SDK Server over stdio initializes, calls a tool with arguments, "
            "and receives notifications and results over the child process's stdin/stdout."
        ),
        transports=("stdio",),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Hosting: session lifecycle
    # ═══════════════════════════════════════════════════════════════════════════
    "hosting:session:cors-expose": Requirement(
        source="sdk",
        behavior="CORS configuration exposes the Mcp-Session-Id header so browser clients can read it.",
        transports=("streamable-http",),
        deferred="Not implemented in the SDK: CORS configuration is left to the hosting ASGI application.",
    ),
    "hosting:session:create": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior=(
            "An initialize POST without a session id creates a session and returns Mcp-Session-Id in the "
            "response headers."
        ),
        transports=("streamable-http",),
    ),
    "hosting:session:delete": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior="DELETE with a valid Mcp-Session-Id terminates the session.",
        transports=("streamable-http",),
    ),
    "hosting:session:id-charset": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior="Generated Mcp-Session-Id values contain only visible ASCII characters.",
        transports=("streamable-http",),
    ),
    "hosting:session:isolation": Requirement(
        source="sdk",
        behavior="Each session gets its own server instance; closing one session does not affect others.",
        transports=("streamable-http",),
    ),
    "hosting:session:missing-id": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior="A non-initialize POST without Mcp-Session-Id in stateful mode returns 400.",
        transports=("streamable-http",),
    ),
    "hosting:session:post-termination-404": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior=(
            "After a session is terminated, any further request carrying that session ID is answered with "
            "404 Not Found."
        ),
        transports=("streamable-http",),
    ),
    "hosting:session:reinitialize": Requirement(
        source="sdk",
        behavior="A second initialize on an already-initialized session transport is rejected.",
        transports=("streamable-http",),
        divergence=Divergence(
            note=(
                "The transport forwards a second initialize carrying the existing session ID to the running "
                "server, which answers it as a fresh handshake; nothing rejects re-initialization."
            ),
        ),
    ),
    "hosting:session:reuse": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior="A POST carrying a valid Mcp-Session-Id routes to that session's transport with state preserved.",
        transports=("streamable-http",),
    ),
    "hosting:session:unknown-id": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior="A POST, GET, or DELETE with an unknown Mcp-Session-Id returns 404.",
        transports=("streamable-http",),
    ),
    "hosting:stateless:concurrent-clients": Requirement(
        source="sdk",
        behavior="Multiple independent clients can connect to a stateless server concurrently.",
        transports=("streamable-http",),
    ),
    "hosting:stateless:no-reuse": Requirement(
        source="sdk",
        behavior="A stateless per-request transport cannot be reused for a second request.",
        transports=("streamable-http",),
    ),
    "hosting:stateless:no-session-id": Requirement(
        source="sdk",
        behavior="In stateless mode no Mcp-Session-Id is emitted and no session validation is performed.",
        transports=("streamable-http",),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Hosting: auth
    # ═══════════════════════════════════════════════════════════════════════════
    "hosting:auth:as-router": Requirement(
        source="sdk",
        behavior=(
            "The authorization-server routes expose the authorize, token, and registration endpoints "
            "(and revocation when supported)."
        ),
        transports=("streamable-http",),
    ),
    "hosting:auth:aud-validation": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#access-token-usage",
        behavior="The resource server validates that the token audience matches its resource identifier.",
        transports=("streamable-http",),
        divergence=Divergence(
            note=(
                "BearerAuthBackend never inspects AccessToken.resource; a token issued for a different "
                "resource is accepted. Spec MUST."
            ),
        ),
    ),
    "hosting:auth:authinfo-propagates": Requirement(
        source="sdk",
        behavior="A valid token's auth info is exposed to request handlers.",
        transports=("streamable-http",),
    ),
    "hosting:auth:expired-401": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#token-handling",
        behavior="An expired token returns 401 invalid_token.",
        transports=("streamable-http",),
        divergence=Divergence(
            note="The challenge carries no `scope` parameter; see the note on hosting:auth:missing-401.",
        ),
    ),
    "hosting:auth:invalid-401": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#token-handling",
        behavior="A malformed bearer token or token-verification failure returns 401 with WWW-Authenticate.",
        transports=("streamable-http",),
        divergence=Divergence(
            note="The challenge carries no `scope` parameter; see the note on hosting:auth:missing-401.",
        ),
    ),
    "hosting:auth:metadata-endpoints": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#authorization-server-location",
        behavior=(
            "The MCP server publishes protected-resource metadata at its well-known endpoint, and the "
            "authorization server (which the SDK can also host) publishes authorization-server metadata "
            "at its own."
        ),
        transports=("streamable-http",),
    ),
    "hosting:auth:missing-401": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#protected-resource-metadata-discovery-requirements",
        behavior=(
            "A request without an Authorization header is rejected with 401; the WWW-Authenticate header "
            "carries resource_metadata (one of the spec's two permitted discovery mechanisms)."
        ),
        transports=("streamable-http",),
        divergence=Divergence(
            note=(
                "The SDK never emits a `scope` parameter in any WWW-Authenticate challenge — neither the "
                "discovery-time 401 (#protected-resource-metadata-discovery-requirements SHOULD) nor the "
                "runtime 403 (#runtime-insufficient-scope-errors SHOULD); and for the no-credentials case "
                'it emits error="invalid_token", which RFC 6750 Section 3.1 says SHOULD NOT appear when no '
                "authentication information was presented."
            ),
        ),
    ),
    "hosting:auth:prm:authorization-servers-field": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#authorization-server-location",
        behavior=(
            "The protected-resource metadata document includes an authorization_servers array with at least one entry."
        ),
        transports=("streamable-http",),
    ),
    "hosting:auth:query-token-ignored": Requirement(
        source="sdk",
        behavior=(
            "An access token presented in the URI query string is not accepted; the request is treated as "
            "unauthenticated."
        ),
        transports=("streamable-http",),
    ),
    "hosting:auth:scope-403": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#runtime-insufficient-scope-errors",
        behavior=(
            "A token lacking a required scope returns 403 with WWW-Authenticate carrying "
            "insufficient_scope, the required scope, and resource_metadata."
        ),
        transports=("streamable-http",),
        divergence=Divergence(
            note=(
                'The SDK emits error="insufficient_scope" and error_description but never the `scope` '
                "parameter the spec SHOULD include; the SDK client reads `scope` from this header to drive "
                "step-up (utils.py extract_scope_from_www_auth) — a resource-server/client asymmetry."
            ),
        ),
    ),
    "hosting:auth:as:authorize-requires-pkce": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#authorization-code-protection",
        behavior=(
            "The bundled authorization endpoint rejects an authorize request that omits "
            "`code_challenge` with `invalid_request`."
        ),
        transports=("streamable-http",),
    ),
    "hosting:auth:as:verifier-mismatch": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#authorization-code-protection",
        behavior=(
            "The bundled token endpoint rejects an authorization-code exchange whose `code_verifier` "
            "does not hash to the stored `code_challenge` with `invalid_grant`."
        ),
        transports=("streamable-http",),
    ),
    "hosting:auth:as:code-single-use": Requirement(
        source="sdk",
        behavior=(
            "An authorization code can be exchanged exactly once; a second exchange of the same code "
            "is rejected with `invalid_grant`. Enforced by the provider deleting the code on first use; "
            "the handler relies on `load_authorization_code` returning None."
        ),
        transports=("streamable-http",),
    ),
    "hosting:auth:as:redirect-uri-binding": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#open-redirection",
        behavior=(
            "The bundled token endpoint rejects an authorization-code exchange whose `redirect_uri` "
            "differs from the one used at authorize; the bundled authorize endpoint rejects a "
            "`redirect_uri` not in the client's registered list without redirecting to it."
        ),
        transports=("streamable-http",),
        divergence=Divergence(
            note=(
                "RFC 6749 §5.2 assigns redirect_uri mismatch at the token endpoint to invalid_grant; "
                "the SDK's TokenHandler returns invalid_request (src/mcp/server/auth/handlers/token.py:157). "
                "The rejection itself is the security-relevant property and is correct."
            ),
        ),
    ),
    "hosting:auth:as:redirect-uri-scheme": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#communication-security",
        behavior=(
            "The bundled registration endpoint accepts only redirect URIs that use HTTPS or target a loopback host."
        ),
        transports=("streamable-http",),
        divergence=Divergence(
            note=(
                "Not enforced: the registration handler models redirect_uris as AnyUrl with no scheme or "
                "host check, so http://evil.example/callback is accepted and registered. The spec's "
                "localhost-or-HTTPS rule is left to the provider implementation."
            ),
        ),
    ),
    "hosting:auth:as:token-cache-headers": Requirement(
        source="sdk",
        behavior=("Every token-endpoint response carries `Cache-Control: no-store` and `Pragma: no-cache`."),
        transports=("streamable-http",),
    ),
    "hosting:auth:as:register-error-response": Requirement(
        source="sdk",
        behavior=(
            "The bundled registration endpoint answers invalid client metadata with HTTP 400 and an "
            "RFC 7591 error body."
        ),
        transports=("streamable-http",),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Hosting: resumability
    # ═══════════════════════════════════════════════════════════════════════════
    "hosting:resume:bad-event-id": Requirement(
        source="sdk",
        behavior="A Last-Event-ID that cannot be mapped to a stream is rejected.",
        transports=("streamable-http",),
        divergence=Divergence(
            note=(
                "The replay path returns an empty SSE stream rather than rejecting an unknown "
                "Last-Event-ID; the client cannot tell an unknown ID apart from a stream with no missed "
                "events."
            ),
        ),
    ),
    "hosting:resume:buffered-replay": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#resumability-and-redelivery",
        behavior="Notifications emitted while no client is connected are replayed in order on reconnect.",
        transports=("streamable-http",),
    ),
    "hosting:resume:close-stream": Requirement(
        source="sdk",
        behavior="Handlers can close an SSE stream cleanly when an event store is configured.",
        transports=("streamable-http",),
    ),
    "hosting:resume:event-ids": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#resumability-and-redelivery",
        behavior="With an event store configured, every SSE event carries an id field.",
        transports=("streamable-http",),
    ),
    "hosting:resume:priming": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior=(
            "A server-initiated SSE stream begins with a priming event carrying an event ID and an empty "
            "data field; a server that closes the connection before terminating the stream sends an SSE "
            "retry field first."
        ),
        transports=("streamable-http",),
        divergence=Divergence(
            note=(
                "The retry hint is attached to the priming event itself rather than sent as a separate "
                "event before the connection closes, and a priming event is only sent when an event store "
                "is configured and the negotiated protocol version is at least 2025-11-25."
            ),
        ),
    ),
    "hosting:resume:replay": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#resumability-and-redelivery",
        behavior="GET with Last-Event-ID replays stored events for that stream after the given id.",
        transports=("streamable-http",),
    ),
    "hosting:resume:stream-scoped": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#resumability-and-redelivery",
        behavior="Replay via Last-Event-ID returns only messages from the stream that event id belongs to.",
        transports=("streamable-http",),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Hosting: HTTP semantics
    # ═══════════════════════════════════════════════════════════════════════════
    "hosting:http:accept-406": Requirement(
        source="sdk",
        behavior="A request whose Accept header does not allow the response representation returns 406.",
        transports=("streamable-http",),
    ),
    "hosting:http:batch": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior=(
            "A POST body is a single JSON-RPC message; batched arrays are rejected for protocol revisions "
            "that forbid them."
        ),
        transports=("streamable-http",),
    ),
    "hosting:http:content-type-415": Requirement(
        source="sdk",
        behavior="A POST with a Content-Type other than application/json returns 415.",
        transports=("streamable-http",),
        divergence=Divergence(
            note=(
                "The transport-security middleware rejects a non-JSON Content-Type with 400 'Invalid "
                "Content-Type header' before the request reaches the transport, so the transport's own 415 "
                "path is unreachable through any public entry point."
            ),
        ),
    ),
    "hosting:http:disconnect-not-cancel": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior=(
            "A client connection drop during an in-flight request does not cancel the server-side "
            "handler; the request continues and its result remains retrievable."
        ),
        transports=("streamable-http",),
    ),
    "hosting:http:dns-rebinding": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#security-warning",
        behavior=(
            "The Origin header is validated on every incoming connection; a request with an invalid "
            "Origin is rejected with 403 Forbidden."
        ),
        transports=("streamable-http",),
        divergence=Divergence(
            note=(
                "The spec's Origin validation is an unconditional MUST; the SDK enables it only when the "
                "host is a localhost address or explicit TransportSecuritySettings are passed (with no "
                "settings, no Origin validation runs), and additionally validates the Host header "
                "(returning 421 on mismatch), which the spec does not require."
            ),
        ),
    ),
    "hosting:http:json-response-mode": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior="With JSON response mode enabled, POST returns application/json instead of SSE.",
        transports=("streamable-http",),
    ),
    "hosting:http:method-405": Requirement(
        source="sdk",
        behavior="An unsupported HTTP method on the MCP endpoint returns 405.",
        transports=("streamable-http",),
    ),
    "hosting:http:no-broadcast": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#multiple-connections",
        behavior=(
            "When multiple SSE streams are open for a session, each server-originated message is sent on "
            "exactly one stream, never duplicated."
        ),
        transports=("streamable-http",),
    ),
    "hosting:http:notifications-202": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior="A POST containing only notifications or responses returns 202 with no body.",
        transports=("streamable-http",),
    ),
    "hosting:http:onerror": Requirement(
        source="sdk",
        behavior="Transport-level rejections are reported through an error callback on the server transport.",
        transports=("streamable-http",),
        deferred="Not implemented in the SDK: the server transport has no error callback; rejections are logged.",
    ),
    "hosting:http:parse-error-400": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior=(
            "A POST body that is not valid JSON or not a valid JSON-RPC message is rejected with HTTP 400; "
            "the body may carry a JSON-RPC error response (the SDK sends a Parse error body)."
        ),
        transports=("streamable-http",),
    ),
    "hosting:http:protocol-version-400": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#protocol-version-header",
        behavior="An invalid or unsupported MCP-Protocol-Version header returns 400 Bad Request.",
        transports=("streamable-http",),
    ),
    "hosting:http:protocol-version-default": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#protocol-version-header",
        behavior=(
            "When no MCP-Protocol-Version header is received and the version cannot be determined another "
            "way, the server assumes protocol version 2025-03-26."
        ),
        transports=("streamable-http",),
    ),
    "hosting:http:response-same-connection": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior=(
            "A response is delivered on the SSE stream opened by the POST that carried its request (or "
            "that stream's resumed continuation), not on an unrelated stream."
        ),
        transports=("streamable-http",),
    ),
    "hosting:http:second-sse-rejected": Requirement(
        source="sdk",
        behavior="A second concurrent standalone GET SSE stream on the same session is rejected.",
        transports=("streamable-http",),
    ),
    "hosting:http:sse-close-after-response": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior="The server terminates a POST-initiated SSE stream after writing the JSON-RPC response.",
        transports=("streamable-http",),
    ),
    "hosting:http:standalone-sse": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#listening-for-messages-from-the-server",
        behavior="GET opens a standalone SSE stream that receives server-initiated messages.",
        transports=("streamable-http",),
    ),
    "hosting:http:standalone-sse-no-response": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#listening-for-messages-from-the-server",
        behavior=(
            "The standalone GET SSE stream carries server requests and notifications but never a JSON-RPC "
            "response, except when resuming a prior request stream."
        ),
        transports=("streamable-http",),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Client transport: streamable HTTP
    # ═══════════════════════════════════════════════════════════════════════════
    "client-transport:http:404-surfaces": Requirement(
        source="sdk",
        behavior="A 404 (session expired) on a request surfaces as an error to the caller.",
        transports=("streamable-http",),
    ),
    "client-transport:http:session-404-reinitialize": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior=(
            "A 404 in response to a request carrying a session ID makes the client start a new session "
            "with a fresh InitializeRequest and no session ID attached."
        ),
        transports=("streamable-http",),
        divergence=Divergence(
            note=(
                "The client surfaces the 404 as an error to the caller instead of re-initializing a new "
                "session; the spec's MUST is not satisfied."
            ),
        ),
        deferred=(
            "Not implemented in the SDK: the client surfaces a Session terminated error instead of "
            "re-initializing (the surfaced error is pinned by client-transport:http:404-surfaces)."
        ),
    ),
    "client-transport:http:accept-header-get": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#listening-for-messages-from-the-server",
        behavior="The client GET to the MCP endpoint includes an Accept header listing text/event-stream.",
        transports=("streamable-http",),
    ),
    "client-transport:http:accept-header-post": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior=(
            "Every client POST to the MCP endpoint includes an Accept header listing both application/json "
            "and text/event-stream."
        ),
        transports=("streamable-http",),
    ),
    "client-transport:http:concurrent-streams": Requirement(
        source="sdk",
        behavior="Multiple concurrent POST-initiated SSE streams each deliver their response to the right caller.",
        transports=("streamable-http",),
    ),
    "client-transport:http:custom-client": Requirement(
        source="sdk",
        behavior=(
            "A caller-supplied HTTP client (and its event hooks and headers) is used for all MCP traffic, "
            "including auth flows."
        ),
        transports=("streamable-http",),
    ),
    "client-transport:http:custom-headers": Requirement(
        source="sdk",
        behavior="Caller-supplied headers are sent on every POST, GET, and DELETE to the MCP endpoint.",
        transports=("streamable-http",),
    ),
    "client-transport:http:json-response-parsed": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior="A Content-Type application/json response is parsed as a single JSON-RPC message.",
        transports=("streamable-http",),
    ),
    "client-transport:http:no-reconnect-after-close": Requirement(
        source="sdk",
        behavior="After the transport is closed, no further reconnection attempts are scheduled.",
        transports=("streamable-http",),
    ),
    "client-transport:http:no-reconnect-after-response": Requirement(
        source="sdk",
        behavior="A POST-initiated stream that already delivered its response is not reconnected when it closes.",
        transports=("streamable-http",),
    ),
    "client-transport:http:protocol-version-header": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#protocol-version-header",
        behavior=(
            "After initialization, the client sends the negotiated MCP-Protocol-Version header on every "
            "subsequent HTTP request."
        ),
        transports=("streamable-http",),
    ),
    "client-transport:http:protocol-version-stored": Requirement(
        source="sdk",
        behavior=(
            "The client transport stores the negotiated protocol version and sends it on every subsequent request."
        ),
        transports=("streamable-http",),
    ),
    "client-transport:http:reconnect-get": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#resumability-and-redelivery",
        behavior=(
            "A standalone GET SSE stream that errors is reconnected with the Last-Event-ID of the last received event."
        ),
        transports=("streamable-http",),
        deferred=(
            "The server's standalone GET stream emits no priming event or retry hint, so the client's "
            "reconnection path always sleeps the hard-coded 1 s default; a deterministic in-process test "
            "would require accepting that real-time wait. The POST-stream reconnection path is covered "
            "by client-transport:http:reconnect-post-priming."
        ),
    ),
    "client-transport:http:reconnect-post-priming": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior=(
            "A POST-initiated SSE stream that errors before delivering its response is reconnected only "
            "if a priming event (an event carrying an ID) was received on it."
        ),
        transports=("streamable-http",),
    ),
    "client-transport:http:reconnect-retry-value": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior="Reconnection delay honours the server-provided SSE retry value when one was sent.",
        transports=("streamable-http",),
    ),
    "client-transport:http:resume-stream-api": Requirement(
        source="sdk",
        behavior=(
            "The client can capture a resumption token, reconnect with the same session id, and receive "
            "the notifications it missed."
        ),
        transports=("streamable-http",),
    ),
    "client-transport:http:session-stored": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior=(
            "The Mcp-Session-Id returned by initialize is stored by the client transport and sent on "
            "every subsequent request."
        ),
        transports=("streamable-http",),
    ),
    "client-transport:http:sse-405-tolerated": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#listening-for-messages-from-the-server",
        behavior="Opening the standalone GET SSE stream tolerates a 405 response without failing the connection.",
        transports=("streamable-http",),
    ),
    "client-transport:http:terminate-405-ok": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior="Session termination succeeds without error if the server answers 405 (termination unsupported).",
        transports=("streamable-http",),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Client auth
    # ═══════════════════════════════════════════════════════════════════════════
    "client-auth:401-after-auth-throws": Requirement(
        source="sdk",
        behavior=(
            "If the server still returns 401 after a successful authorization, the client fails instead of looping."
        ),
        transports=("streamable-http",),
    ),
    "client-auth:401-triggers-flow": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#protected-resource-metadata-discovery-requirements",
        behavior="A 401 on a request triggers the OAuth authorization flow once.",
        transports=("streamable-http",),
    ),
    "client-auth:403-scope-upgrade": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#step-up-authorization-flow",
        behavior=(
            "A 403 with WWW-Authenticate triggers a scope-upgrade authorization attempt; repeated 403s do not loop."
        ),
        transports=("streamable-http",),
    ),
    "client-auth:as-metadata-discovery:priority-order": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#authorization-server-metadata-discovery",
        behavior=(
            "The client discovers authorization-server metadata by trying, in order, the OAuth "
            "path-inserted, OIDC path-inserted, and OIDC path-appended well-known URLs (with the "
            "root-path forms when the issuer URL has no path)."
        ),
        transports=("streamable-http",),
    ),
    "client-auth:as-metadata-discovery:issuer-validation": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#authorization-server-metadata-discovery",
        behavior=(
            "The client rejects authorization-server metadata whose issuer does not match the URL the "
            "metadata was retrieved from (RFC 8414 section 3.3)."
        ),
        transports=("streamable-http",),
        divergence=Divergence(
            note=(
                "The SDK parses authorization-server metadata without comparing issuer to the discovery "
                "URL; a mismatched issuer is accepted and the flow proceeds."
            ),
        ),
    ),
    "client-auth:authorize:error-surfaces": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#authorization-flow-steps",
        behavior=(
            "An OAuth error redirect from the authorize endpoint aborts the flow before any token "
            "request is issued, surfacing as an error to the caller."
        ),
        transports=("streamable-http",),
        divergence=Divergence(
            note=(
                "The callback contract has no error form, so the client surfaces 'No authorization code "
                "received' rather than the redirect's `error`/`error_description` values."
            ),
        ),
    ),
    "client-auth:authorize:offline-access-consent": Requirement(
        source="sdk",
        behavior=(
            "When the authorization server's metadata advertises offline_access in scopes_supported and "
            "the client uses the refresh_token grant, offline_access is appended to the requested scope "
            "and prompt=consent is added to the authorize request."
        ),
        transports=("streamable-http",),
    ),
    "client-auth:bearer-header:every-request": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#token-requirements",
        behavior=(
            "Once authorized, the client sends the bearer token in the Authorization header on every HTTP "
            "request to the MCP server, never in the query string."
        ),
        transports=("streamable-http",),
    ),
    "client-auth:cimd": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#client-id-metadata-documents",
        behavior="The client can use a client-ID metadata document URL as its OAuth client_id instead of registration.",
        transports=("streamable-http",),
    ),
    "client-auth:client-credentials": Requirement(
        source="sdk",
        behavior=(
            "A client-credentials provider obtains a token without user interaction and the resulting "
            "bearer token authorizes subsequent requests."
        ),
        transports=("streamable-http",),
    ),
    "client-auth:dcr:registration-error-surfaces": Requirement(
        source="sdk",
        behavior=(
            "A 400 from the registration endpoint surfaces to the caller as an OAuthRegistrationError "
            "carrying the status and the server's RFC 7591 error body."
        ),
        transports=("streamable-http",),
    ),
    "client-auth:dcr": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#dynamic-client-registration",
        behavior=(
            "The client performs dynamic client registration against the authorization server when no "
            "client_id is preconfigured."
        ),
        transports=("streamable-http",),
    ),
    "client-auth:invalid-client-clears-all": Requirement(
        source="sdk",
        behavior=(
            "An invalid-client or unauthorized-client error during authorization invalidates all stored credentials."
        ),
        transports=("streamable-http",),
        divergence=Divergence(
            note=(
                "The token-response handlers do not parse the error body; an invalid_client or "
                "unauthorized_client response leaves stored client_info untouched. The TypeScript SDK "
                "clears it."
            ),
        ),
        deferred=(
            "Not implemented in the SDK: no token-response path inspects the error code to decide "
            "whether to clear client_info."
        ),
    ),
    "client-auth:invalid-grant-clears-tokens": Requirement(
        source="sdk",
        behavior="An invalid-grant error during authorization invalidates only the stored tokens.",
        transports=("streamable-http",),
    ),
    "client-auth:pkce:refuse-if-unsupported": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#authorization-code-protection",
        behavior=(
            "The client refuses to proceed when the authorization server's metadata does not include "
            "code_challenge_methods_supported, since PKCE support cannot be verified."
        ),
        transports=("streamable-http",),
        divergence=Divergence(
            note=(
                "The client never inspects code_challenge_methods_supported and proceeds with PKCE S256 "
                "regardless; the spec MUST is not enforced."
            ),
        ),
    ),
    "client-auth:pkce:s256": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#authorization-code-protection",
        behavior=(
            "The authorization request includes a PKCE S256 code challenge and the token request includes "
            "the matching verifier."
        ),
        transports=("streamable-http",),
    ),
    "client-auth:pre-registration": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#preregistration",
        behavior=(
            "A client with statically preconfigured credentials skips dynamic registration and uses them directly."
        ),
        transports=("streamable-http",),
    ),
    "client-auth:private-key-jwt": Requirement(
        source="sdk",
        behavior="The client can authenticate the client-credentials grant with a signed JWT assertion.",
        transports=("streamable-http",),
    ),
    "client-auth:prm-discovery:fallback-order": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#protected-resource-metadata-discovery-requirements",
        behavior=(
            "The client uses resource_metadata from WWW-Authenticate when present, then falls back to the "
            "well-known protected-resource locations in the documented order."
        ),
        transports=("streamable-http",),
    ),
    "client-auth:prm-discovery:no-prm-fallback": Requirement(
        source="sdk",
        behavior=(
            "When every protected-resource metadata probe fails, the client falls back to discovering "
            "authorization-server metadata directly at the MCP server's origin (the legacy 2025-03-26 path) "
            "rather than aborting."
        ),
        transports=("streamable-http",),
    ),
    "client-auth:prm-resource-mismatch": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#authorization-server-location",
        behavior=(
            "The client refuses to proceed when the protected-resource metadata's resource field does not "
            "match the server URL it is connecting to."
        ),
        transports=("streamable-http",),
    ),
    "client-auth:refresh:transparent": Requirement(
        source="sdk",
        behavior=(
            "An access token the client considers expired is transparently refreshed before the next "
            "request, using the stored refresh token; the refresh request includes the resource indicator "
            "and the new token is persisted."
        ),
        transports=("streamable-http",),
    ),
    "client-auth:resource-parameter": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#resource-parameter-implementation",
        behavior=(
            "The client includes the canonical server URI as the resource parameter in both the "
            "authorization request and the token request."
        ),
        transports=("streamable-http",),
    ),
    "client-auth:scope-selection:priority": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#scope-selection-strategy",
        behavior=(
            "Client selects requested scope from the WWW-Authenticate scope param if present; otherwise "
            "uses scopes_supported from the PRM document; otherwise omits scope."
        ),
        transports=("streamable-http",),
        divergence=Divergence(
            note=(
                "The SDK inserts an extra fallback step between PRM and omit: if the authorization "
                "server metadata advertises scopes_supported, that list is used (client/auth/utils.py). "
                "This is beyond the spec's two-step chain."
            ),
        ),
    ),
    "client-auth:state:verify": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#open-redirection",
        behavior=(
            "A state parameter is included in the authorization URL, and authorization results with a "
            "missing or mismatched state are discarded."
        ),
        transports=("streamable-http",),
    ),
    "client-auth:token-endpoint-auth-method": Requirement(
        source="sdk",
        behavior="The client authenticates to the token endpoint using the auth method established at registration.",
        transports=("streamable-http",),
    ),
    "client-auth:token-provenance": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#token-handling",
        behavior=(
            "The client sends the MCP server only tokens issued by that server's authorization server, "
            "never tokens obtained elsewhere."
        ),
        transports=("streamable-http",),
        deferred=(
            "Untestable negative through the public API: there is no path to inject a token obtained "
            "elsewhere into the auth provider's state, so the absence cannot be observed end to end."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # stdio transport
    # ═══════════════════════════════════════════════════════════════════════════
    "transport:stdio:clean-shutdown": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#shutdown",
        behavior="Closing the client transport closes the child process's stdin and the server exits cleanly.",
        transports=("stdio",),
    ),
    "transport:stdio:stream-purity": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#stdio",
        behavior=(
            "Nothing that is not a valid MCP message is written to the server's stdout, and nothing that "
            "is not a valid MCP message is written to its stdin."
        ),
        transports=("stdio",),
        divergence=Divergence(
            note=(
                "stdio_server's own writes satisfy this, but it does not redirect or guard sys.stdout: "
                "handler code that calls print() writes directly to the protocol stream and corrupts the "
                "framing. The spec MUST is satisfied only as long as application code behaves."
            ),
        ),
    ),
    "transport:stdio:no-embedded-newlines": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#stdio",
        behavior="Serialized JSON-RPC messages on stdio contain no embedded newlines; one message per line.",
        transports=("stdio",),
    ),
    "transport:stdio:shutdown-escalation": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#stdio",
        behavior=(
            "If the server process does not exit after stdin is closed, the client transport terminates "
            "it (and kills it if still alive) after a grace period."
        ),
        transports=("stdio",),
        deferred=(
            "A server that ignores stdin close takes the full PROCESS_TERMINATION_TIMEOUT (2.0 s) grace "
            "period plus up to a further 2.0 s for SIGTERM/SIGKILL escalation; testing that path is "
            "real-time-bound (the constant is module-level with no public override) and so is deliberately "
            "excluded from this suite. Covered by tests/client/test_stdio.py."
        ),
    ),
    "transport:stdio:stderr-passthrough": Requirement(
        source="sdk",
        behavior="Server stderr is available to the client and is not consumed by the transport.",
        transports=("stdio",),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Composite end-to-end flows
    # ═══════════════════════════════════════════════════════════════════════════
    "flow:compat:dual-transport-server": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#backwards-compatibility",
        behavior=(
            "A single server instance can serve streamable HTTP and the legacy SSE transport "
            "concurrently; clients on either transport can call the same tools."
        ),
        transports=("streamable-http", "sse"),
    ),
    "flow:compat:streamable-then-sse-fallback": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#backwards-compatibility",
        behavior=(
            "When a streamable HTTP initialize fails with 400, 404, or 405, falling back to the legacy "
            "SSE client transport against the same server connects successfully."
        ),
        transports=("streamable-http", "sse"),
        divergence=Divergence(
            note=(
                "The SDK provides no automatic streamable-HTTP-to-SSE client fallback; the spec's "
                "client-side SHOULD is left to the application to compose from streamable_http_client "
                "and sse_client. Both halves are independently proven by the matrix."
            ),
        ),
        deferred=(
            "A demonstration test would only re-prove what the matrix already covers (an SSE-only "
            "server is reachable via sse_client; an unmounted route returns 404), with the application "
            "doing the fallback in between rather than the SDK."
        ),
    ),
    "flow:elicitation:multi-step-form": Requirement(
        source="sdk",
        behavior=(
            "A single tool handler issues sequential elicitations; an accept on one step feeds the next, "
            "and a decline or cancel at any step short-circuits to a final result."
        ),
    ),
    "flow:elicitation:url-at-session-init": Requirement(
        source="sdk",
        behavior=(
            "The server can issue a URL-mode elicitation over the standalone GET stream immediately after "
            "session initialization, before any client request."
        ),
        transports=("streamable-http",),
        deferred=(
            "Not implemented in the SDK: no public per-session post-initialization hook exists on either "
            "server flavour (Server.lifespan runs at server startup, not per session; ServerSession "
            "handles the initialized notification internally with no callback). Driving 'before any "
            "client request' deterministically would also require knowing the standalone GET stream is "
            "established, which has no synchronization signal."
        ),
    ),
    "flow:elicitation:url-required-then-retry": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#url-elicitation-required-error",
        behavior=(
            "A tool call rejected with the URL-elicitation-required error can be retried successfully "
            "after the client completes the URL flow and the server announces completion."
        ),
    ),
    "flow:multi-client:stateful-isolation": Requirement(
        source="sdk",
        behavior=(
            "Independent clients connected to one stateful server each receive a distinct session and "
            "only the notifications produced by their own requests."
        ),
        transports=("streamable-http",),
    ),
    "flow:oauth:authorization-code-roundtrip": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#authorization-flow-steps",
        behavior=(
            "Connecting to a protected server walks the authorization-code flow end to end: the first "
            "attempt requires authorization, the code is exchanged, and a subsequent connection succeeds."
        ),
        transports=("streamable-http",),
    ),
    "flow:resume:tool-call-resumption-token": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#resumability-and-redelivery",
        behavior=(
            "A tool call interrupted mid-stream is transparently resumed by the client transport using "
            "the last-seen event id, delivering only the remaining notifications and the final result."
        ),
        transports=("streamable-http",),
    ),
    "flow:session:terminate-then-reconnect": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior=("After terminating a session, a fresh connection obtains a new session id and operations succeed."),
        transports=("streamable-http",),
    ),
    "flow:tool-result:resource-link-follow": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#resource-links",
        behavior=(
            "A resource_link returned by a tool call can be followed with resources/read on the linked "
            "URI to retrieve the referenced contents."
        ),
    ),
}


def requirement(requirement_id: str) -> Callable[[_TestFn], _TestFn]:
    """Mark a test as exercising a requirement from :data:`REQUIREMENTS`.

    Applies the `requirement` pytest marker and records the coverage link checked by
    `test_coverage.py`. Unknown IDs fail at import time so a typo surfaces as a collection
    error on the offending test, not as a missing-coverage report later.
    """
    if requirement_id not in REQUIREMENTS:
        raise KeyError(f"Unknown requirement id {requirement_id!r}: add it to REQUIREMENTS in {__name__}")

    def apply(test_fn: _TestFn) -> _TestFn:
        covered_by(requirement_id).append(f"{test_fn.__module__}.{test_fn.__qualname__}")
        return pytest.mark.requirement(requirement_id)(test_fn)

    return apply


_COVERAGE: dict[str, list[str]] = {}


def covered_by(requirement_id: str) -> list[str]:
    """Return the (mutable) list of test names recorded as exercising `requirement_id`."""
    return _COVERAGE.setdefault(requirement_id, [])
