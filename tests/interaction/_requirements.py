"""Requirements manifest for the interaction-model test suite.

Every user-facing behaviour the SDK must satisfy, keyed by a stable `<area>:<feature>[:<variant>]`
ID. Each entry owns the tests that exercise it: tests declare `@requirement("<id>")` and
`test_coverage.py` enforces that every non-deferred requirement is exercised by at least one test.

Sources:
    spec URL    -- externally mandated by the MCP specification (deep link to the section)
    `sdk`       -- a behavioural guarantee the SDK chose; not spec-mandated
    `issue:#n`  -- regression lock-in for a previously fixed bug

The `behavior` sentence describes what the suite *asserts* -- which is always the SDK's current
behaviour. Where that differs from what `source` mandates, the gap is recorded in `divergence`
and the tests still pin current behaviour: this suite is the parity bar for the receive-path
rewrite, so a test that fails today proves nothing about equivalence.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

import pytest

SPEC_REVISION = "2025-11-25"
SPEC_BASE_URL = f"https://modelcontextprotocol.io/specification/{SPEC_REVISION}"

_TestFn = TypeVar("_TestFn", bound=Callable[..., object])


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
    divergence: Divergence | None = None
    deferred: str | None = None


REQUIREMENTS: dict[str, Requirement] = {
    # ═══════════════════════════════════════════════════════════════════════════
    # Protocol primitives
    # ═══════════════════════════════════════════════════════════════════════════
    "protocol:error:internal-error": Requirement(
        source=f"{SPEC_BASE_URL}/basic#responses",
        behavior="An unhandled exception in a request handler is returned to the caller as a JSON-RPC error.",
        divergence=Divergence(
            note=(
                "The spec reserves -32603 Internal error for this; the low-level Server returns code 0 "
                "(not a defined JSON-RPC code) and leaks str(exc) as the error message."
            ),
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════════════════════════════════════
    "lifecycle:initialize:server-info": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#initialization",
        behavior="The initialize result identifies the server: name and version, plus title when declared.",
    ),
    "lifecycle:initialize:instructions": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#initialization",
        behavior=(
            "Server-declared instructions are returned in the initialize result, and omitted when the "
            "server declares none."
        ),
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
    # ═══════════════════════════════════════════════════════════════════════════
    # Cancellation
    # ═══════════════════════════════════════════════════════════════════════════
    "cancellation:in-flight": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/cancellation#behavior-requirements",
        behavior=(
            "A cancellation notification for an in-flight request stops the server-side handler, and the "
            "caller's pending request fails with an error response."
        ),
        divergence=Divergence(
            note=(
                "The spec says receivers of a cancellation SHOULD NOT send a response for the cancelled "
                "request; the server sends an error response (code 0, 'Request cancelled'), which is what "
                "unblocks the SDK client's pending call."
            ),
        ),
    ),
    "cancellation:server-survives": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/cancellation#behavior-requirements",
        behavior="The session continues to serve new requests after an earlier request was cancelled.",
    ),
    "cancellation:unknown-request": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/cancellation#behavior-requirements",
        behavior=(
            "A cancellation notification referencing an unknown or already-completed request is ignored without error."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Progress
    # ═══════════════════════════════════════════════════════════════════════════
    "progress:server-to-client": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/progress#progress-flow",
        behavior=(
            "Progress notifications emitted by a handler during a request are delivered to the caller's "
            "progress callback, in order, with their progress, total, and message."
        ),
    ),
    "progress:token-propagation": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/progress#progress-flow",
        behavior=(
            "Supplying a progress callback attaches a progress token to the outgoing request, which the "
            "server-side handler can observe in its request metadata."
        ),
    ),
    "progress:no-token": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/progress#progress-flow",
        behavior=(
            "Without a progress callback no token is attached, and a handler that reports progress anyway "
            "sends nothing."
        ),
    ),
    "progress:client-to-server": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/progress#progress-flow",
        behavior="A progress notification sent by the client is delivered to the server's progress handler.",
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Timeouts
    # ═══════════════════════════════════════════════════════════════════════════
    "timeouts:per-request": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#timeouts",
        behavior=(
            "A request that exceeds its read timeout fails with a request-timeout error instead of "
            "waiting forever for the response."
        ),
        divergence=Divergence(
            note=(
                "The spec says the requester SHOULD issue a cancellation notification for the timed-out "
                "request; the client only raises locally and sends nothing, so the server keeps running "
                "the handler."
            ),
        ),
    ),
    "timeouts:session-survives": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#timeouts",
        behavior="The session continues to serve new requests after an earlier request timed out.",
    ),
    "timeouts:session-default": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#timeouts",
        behavior="A session-level read timeout applies to every request that does not override it.",
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Pagination
    # ═══════════════════════════════════════════════════════════════════════════
    "pagination:cursor-round-trip": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/pagination#response-format",
        behavior=(
            "The nextCursor returned by a list handler reaches the client, and the cursor the client "
            "sends back on the next call reaches the handler as an opaque string."
        ),
    ),
    "pagination:exhaustion": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/pagination#response-format",
        behavior=(
            "Following nextCursor until it is absent yields every page exactly once; a result without "
            "nextCursor ends the sequence."
        ),
    ),
    "pagination:resources": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/pagination#operations-supporting-pagination",
        behavior="resources/list supports cursor pagination.",
    ),
    "pagination:resource-templates": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/pagination#operations-supporting-pagination",
        behavior="resources/templates/list supports cursor pagination.",
    ),
    "pagination:prompts": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/pagination#operations-supporting-pagination",
        behavior="prompts/list supports cursor pagination.",
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Request metadata
    # ═══════════════════════════════════════════════════════════════════════════
    "meta:request-to-handler": Requirement(
        source=f"{SPEC_BASE_URL}/basic#meta",
        behavior="The _meta object the client attaches to a request is visible to the server handler.",
    ),
    "meta:result-to-client": Requirement(
        source=f"{SPEC_BASE_URL}/basic#meta",
        behavior="The _meta object a handler attaches to its result is delivered to the client.",
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Ping
    # ═══════════════════════════════════════════════════════════════════════════
    "ping:client-to-server": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/ping#behavior-requirements",
        behavior="A client-initiated ping receives an empty result from the server.",
    ),
    "ping:server-to-client": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/ping#behavior-requirements",
        behavior="A server-initiated ping receives an empty result from the client.",
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Tools
    # ═══════════════════════════════════════════════════════════════════════════
    "tools:list:basic": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#listing-tools",
        behavior="tools/list returns the registered tools with name, description, and inputSchema.",
    ),
    "tools:list:optional-fields": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#tool",
        behavior=(
            "Optional Tool fields supplied by the server (title, annotations, outputSchema, icons, _meta) "
            "are delivered to the client unchanged."
        ),
    ),
    "tools:call:content:text": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#text-content",
        behavior="tools/call delivers arguments to the tool handler and returns its text content to the caller.",
    ),
    "tools:call:content:image": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#image-content",
        behavior="A tool result can carry image content: base64 data with a mimeType.",
    ),
    "tools:call:content:audio": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#audio-content",
        behavior="A tool result can carry audio content: base64 data with a mimeType.",
    ),
    "tools:call:content:resource-link": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#resource-links",
        behavior="A tool result can carry a resource_link content block referencing a resource by URI.",
    ),
    "tools:call:content:embedded-resource": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#embedded-resources",
        behavior="A tool result can carry an embedded resource with full text or blob contents.",
    ),
    "tools:call:content:multiple": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#calling-tools",
        behavior="A tool result can carry multiple content blocks of different types; order is preserved.",
    ),
    "tools:call:structured-content": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#structured-content",
        behavior="A tool result can carry structuredContent alongside content; the client receives both.",
    ),
    "tools:call:is-error": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#error-handling",
        behavior=(
            "A tool execution failure is returned as a result with isError true and the failure described "
            "in content, not as a JSON-RPC error."
        ),
    ),
    "tools:call:unknown-name": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#error-handling",
        behavior="tools/call for a name the server does not recognise returns a JSON-RPC error.",
    ),
    "tools:call:invalid-arguments": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#error-handling",
        behavior=(
            "Arguments that fail the tool's input validation produce a tool execution error (isError true "
            "with the validation failure described in content), not a protocol error."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Completion
    # ═══════════════════════════════════════════════════════════════════════════
    "completion:complete:prompt-ref": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/completion#requesting-completions",
        behavior="completion/complete with a ref/prompt returns suggested values for the named prompt argument.",
    ),
    "completion:complete:resource-ref": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/completion#requesting-completions",
        behavior="completion/complete with a ref/resource returns suggested values for a URI template variable.",
    ),
    "completion:complete:context": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/completion#context",
        behavior="Previously-resolved argument values supplied in context.arguments reach the completion handler.",
    ),
    "completion:complete:not-supported": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/completion#capabilities",
        behavior=(
            "A server with no completion handler does not advertise the completions capability and rejects "
            "completion/complete with METHOD_NOT_FOUND."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Logging
    # ═══════════════════════════════════════════════════════════════════════════
    "logging:set-level": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/logging#log-levels",
        behavior="logging/setLevel delivers the requested level to the server's handler and returns an empty result.",
    ),
    "logging:message:notification": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/logging#log-message-notifications",
        behavior=(
            "A log message sent by a server handler is delivered to the client's logging callback with its "
            "severity level, logger name, and data, in the order the server sent them."
        ),
    ),
    "logging:message:all-levels": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/logging#log-levels",
        behavior="All eight RFC 5424 severity levels are deliverable as log message notifications.",
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Resources
    # ═══════════════════════════════════════════════════════════════════════════
    "resources:list:basic": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#listing-resources",
        behavior=(
            "resources/list returns the registered resources with uri, name, and the optional descriptive "
            "fields supplied by the server."
        ),
    ),
    "resources:read:text": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#reading-resources",
        behavior="resources/read returns text contents carrying uri, mimeType, and the text.",
    ),
    "resources:read:binary": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#reading-resources",
        behavior="resources/read returns binary contents base64-encoded in blob.",
    ),
    "resources:read:not-found": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#error-handling",
        behavior="resources/read for an unknown URI returns a JSON-RPC error; the spec reserves -32002 for it.",
    ),
    "resources:templates:list": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#resource-templates",
        behavior=(
            "resources/templates/list returns the registered templates with their uriTemplate and descriptive fields."
        ),
    ),
    "resources:subscribe": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#subscriptions",
        behavior="resources/subscribe delivers the URI to the server's subscribe handler and returns an empty result.",
    ),
    "resources:unsubscribe": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#subscriptions",
        behavior=(
            "resources/unsubscribe delivers the URI to the server's unsubscribe handler and returns an empty result."
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
    # Notifications: list_changed (server → client)
    # ═══════════════════════════════════════════════════════════════════════════
    "notifications:tools:list-changed": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#list-changed-notification",
        behavior="A tools/list_changed notification sent by the server reaches the client's message handler.",
    ),
    "notifications:resources:list-changed": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#list-changed-notification",
        behavior="A resources/list_changed notification sent by the server reaches the client's message handler.",
    ),
    "notifications:prompts:list-changed": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#list-changed-notification",
        behavior="A prompts/list_changed notification sent by the server reaches the client's message handler.",
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Prompts
    # ═══════════════════════════════════════════════════════════════════════════
    "prompts:list:basic": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#listing-prompts",
        behavior="prompts/list returns the registered prompts with name, description, and argument declarations.",
    ),
    "prompts:get:arguments": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#getting-a-prompt",
        behavior="prompts/get delivers the supplied arguments to the prompt handler and returns its messages.",
    ),
    "prompts:get:multi-message": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#getting-a-prompt",
        behavior="A prompt can return multiple messages mixing user and assistant roles; order is preserved.",
    ),
    "prompts:get:unknown-name": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#error-handling",
        behavior="prompts/get for an unknown prompt name returns a JSON-RPC error.",
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Sampling (server → client)
    # ═══════════════════════════════════════════════════════════════════════════
    "sampling:create-message:round-trip": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#creating-messages",
        behavior=(
            "A sampling/createMessage request from a server handler is answered by the client's sampling "
            "callback, and the callback's result (role, content, model, stopReason) is returned to the handler."
        ),
    ),
    "sampling:create-message:params": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#creating-messages",
        behavior=(
            "The sampling parameters supplied by the server (messages, maxTokens, systemPrompt, "
            "modelPreferences, temperature, stopSequences) reach the client callback intact."
        ),
    ),
    "sampling:create-message:image-content": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#message-content",
        behavior="Sampling messages can carry image content: base64 data with a mimeType.",
    ),
    "sampling:create-message:client-error": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#error-handling",
        behavior="A sampling callback that returns an error is surfaced to the requesting handler as an MCPError.",
    ),
    "sampling:create-message:not-supported": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#capabilities",
        behavior=(
            "A sampling request to a client that did not declare the sampling capability fails with an "
            "error rather than hanging or being silently dropped."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Elicitation (server → client)
    # ═══════════════════════════════════════════════════════════════════════════
    "elicitation:form:accept": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#form-mode-elicitation",
        behavior=(
            "A form-mode elicitation answered with action 'accept' returns the user's content to the "
            "requesting handler, validated against the requested schema."
        ),
    ),
    "elicitation:form:decline": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#response-actions",
        behavior="A form-mode elicitation answered with action 'decline' returns no content to the handler.",
    ),
    "elicitation:form:cancel": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#response-actions",
        behavior="A form-mode elicitation answered with action 'cancel' returns no content to the handler.",
    ),
    "elicitation:url:accept": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#url-mode-elicitation",
        behavior=(
            "A URL-mode elicitation delivers the message, URL, and elicitationId to the client; an accept "
            "response carries no content (accept means the user agreed to visit the URL, not that the "
            "interaction completed)."
        ),
    ),
    "elicitation:url:decline": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#response-actions",
        behavior="A URL-mode elicitation answered with decline returns the action with no content.",
    ),
    "elicitation:url:cancel": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#response-actions",
        behavior="A URL-mode elicitation answered with cancel returns the action with no content.",
    ),
    "elicitation:complete-notification": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#completion-notification",
        behavior=(
            "An elicitation/complete notification sent by the server after an out-of-band elicitation "
            "finishes reaches the client carrying the elicitationId."
        ),
    ),
    "elicitation:url:required-error": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#url-elicitation-required-error",
        behavior=(
            "A handler that cannot proceed without a URL elicitation rejects the request with error "
            "-32042, carrying the pending elicitations in the error data."
        ),
    ),
    "elicitation:form:not-supported": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#capabilities",
        behavior=(
            "An elicitation request to a client that did not declare the elicitation capability fails with "
            "an error rather than hanging or being silently dropped."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Roots (server → client)
    # ═══════════════════════════════════════════════════════════════════════════
    "roots:list:round-trip": Requirement(
        source=f"{SPEC_BASE_URL}/client/roots#listing-roots",
        behavior=(
            "A roots/list request from a server handler is answered by the client's roots callback, and "
            "the returned roots (uri, name) reach the handler."
        ),
    ),
    "roots:list:empty": Requirement(
        source=f"{SPEC_BASE_URL}/client/roots#listing-roots",
        behavior="An empty roots list is a valid response and reaches the handler as such.",
    ),
    "roots:list:not-supported": Requirement(
        source=f"{SPEC_BASE_URL}/client/roots#capabilities",
        behavior=(
            "A roots/list request to a client that did not declare the roots capability fails with an "
            "error rather than hanging or being silently dropped."
        ),
    ),
    "roots:list-changed": Requirement(
        source=f"{SPEC_BASE_URL}/client/roots#root-list-changes",
        behavior="A roots/list_changed notification sent by the client is delivered to the server's handler.",
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # MCPServer behavioural guarantees (not spec-mandated)
    # ═══════════════════════════════════════════════════════════════════════════
    "mcpserver:tools:output-schema:model": Requirement(
        source="sdk",
        behavior=(
            "A tool returning a typed model advertises a matching generated outputSchema and returns the "
            "model's fields as structuredContent alongside a serialised text block."
        ),
    ),
    "mcpserver:tools:output-schema:wrapped": Requirement(
        source="sdk",
        behavior=(
            "A tool returning a non-object type (primitive or list) wraps the value as {'result': ...} in "
            "structuredContent, with a matching generated outputSchema."
        ),
    ),
    "mcpserver:resources:static": Requirement(
        source="sdk",
        behavior=(
            "A function registered with @mcp.resource() for a fixed URI is listed by resources/list and "
            "served by resources/read at that URI."
        ),
    ),
    "mcpserver:resources:template": Requirement(
        source="sdk",
        behavior=(
            "A function registered with a URI template is listed by resources/templates/list and matched "
            "by resources/read, receiving the parameters extracted from the requested URI."
        ),
    ),
    "mcpserver:resources:unknown-uri": Requirement(
        source="sdk",
        behavior="resources/read for a URI matching no registered resource returns a JSON-RPC error.",
        divergence=Divergence(
            note=(
                "The spec reserves -32002 for resource-not-found; MCPServer raises ResourceError, which "
                "the low-level server converts to error code 0."
            ),
        ),
    ),
    "mcpserver:prompts:decorated": Requirement(
        source="sdk",
        behavior=(
            "A function registered with @mcp.prompt() is listed with arguments derived from its signature "
            "and rendered into prompt messages by prompts/get."
        ),
    ),
    "mcpserver:prompts:unknown-name": Requirement(
        source="sdk",
        behavior="prompts/get for a name that was never registered returns a JSON-RPC error.",
        divergence=Divergence(
            note=(
                "The spec's example uses -32602 Invalid params for unknown prompts; MCPServer raises "
                "ValueError, which the low-level server converts to error code 0."
            ),
        ),
    ),
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
    "mcpserver:tools:handler-exception": Requirement(
        source="sdk",
        behavior=(
            "An exception raised by a tool function (ToolError or otherwise) is caught and returned as a "
            "tool result with isError true and the failure text in content; it does not become a JSON-RPC error."
        ),
    ),
    "mcpserver:tools:unknown-name": Requirement(
        source="sdk",
        behavior="Calling a tool name that was never registered returns a tool result with isError true.",
        divergence=Divergence(
            note=(
                "The spec classifies unknown tools as a protocol error (its example uses -32602 Invalid "
                "params); MCPServer reports a tool execution error instead. The low-level path follows the "
                "spec example (see tools:call:unknown-name)."
            ),
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
