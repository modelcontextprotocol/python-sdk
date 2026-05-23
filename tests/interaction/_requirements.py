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
