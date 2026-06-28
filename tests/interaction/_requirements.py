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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

import pytest
from mcp_types.version import KNOWN_PROTOCOL_VERSIONS

SpecVersion = Literal["2025-11-25", "2026-07-28"]
"""A protocol version the suite parametrizes over. Both values are typed even though only one is
on the active axis (SPEC_VERSIONS) until the 2026-07-28 implementation lands."""

SPEC_VERSIONS: tuple[SpecVersion, ...] = ("2025-11-25", "2026-07-28")
"""The active spec-version matrix axis, ordered oldest to newest. Every entry must be in KNOWN_PROTOCOL_VERSIONS."""

SPEC_BASE_URL = "https://modelcontextprotocol.io/specification/2025-11-25"
"""Deep-link base for entries citing the 2025-11-25 revision (the bulk of the manifest). Pinned --
not derived from SPEC_VERSIONS -- so adding a newer revision to the active axis does not silently
repoint existing source URLs."""

SPEC_2026_BASE_URL = "https://modelcontextprotocol.io/specification/2026-07-28"
"""Deep-link base for entries citing the 2026-07-28 revision."""

Transport = Literal["in-memory", "stdio", "streamable-http", "streamable-http-stateless", "sse"]

CONNECTABLE_TRANSPORTS: tuple[Transport, ...] = ("in-memory", "sse", "streamable-http", "streamable-http-stateless")
"""Transports the connect fixture fans out over (the subset with a factory in conftest._FACTORIES)."""

TRANSPORT_SPEC_VERSIONS: dict[Transport, tuple[SpecVersion, ...]] = {
    "sse": ("2025-11-25",),
    "in-memory": ("2025-11-25", "2026-07-28"),
    # At the newer revision the protocol-version header check runs before the stateless branch is
    # taken, so a stateless connection at that revision behaves identically to the stateful one.
    # Locked to avoid a redundant matrix column; revisit if the header/stateless ordering changes.
    "streamable-http-stateless": ("2025-11-25",),
}
"""Transports that only serve a subset of SPEC_VERSIONS. Absent => serves all. Consulted by compute_cells()."""

ArmExclusionReason = Literal[
    "asserts-legacy-handshake",
    "method-not-in-modern-registry",
    "legacy-only-vocabulary",
    "modern-error-surface",
    "requires-session",
    "drives-transport-directly",
    "server-initiated-request",
]
"""Machine-readable reasons a requirement is excluded from a (transport, spec_version) matrix cell.
The set doubles as a re-admission checklist: when a feature lands, grep for its reason to find the
cells to re-admit. Values are kept byte-identical to the typescript-sdk's EntryExclusionReason."""

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
class ArmExclusion:
    """Excludes a requirement from a (transport, spec_version) matrix cell, with a typed reason."""

    reason: ArmExclusionReason
    transport: Transport | None = None
    spec_version: SpecVersion | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if self.spec_version is not None and self.spec_version not in KNOWN_PROTOCOL_VERSIONS:
            raise ValueError(f"spec_version {self.spec_version!r} is not in KNOWN_PROTOCOL_VERSIONS")


@dataclass(frozen=True, kw_only=True)
class KnownFailure:
    """A (transport, spec_version) cell where the requirement's test is expected to fail (strict xfail)."""

    note: str
    transport: Transport | None = None
    spec_version: SpecVersion | None = None
    issue: str | None = None

    def __post_init__(self) -> None:
        if not self.note.strip():
            raise ValueError("note must be non-empty")
        if self.spec_version is not None and self.spec_version not in KNOWN_PROTOCOL_VERSIONS:
            raise ValueError(f"spec_version {self.spec_version!r} is not in KNOWN_PROTOCOL_VERSIONS")
        if self.issue is not None and not re.fullmatch(r"#\d+|https://github\.com/\S+", self.issue):
            raise ValueError(f"issue must be '#<n>' or a GitHub URL, got {self.issue!r}")


@dataclass(frozen=True, kw_only=True)
class Requirement:
    """A single testable behaviour and the provenance of why it must hold."""

    source: str
    behavior: str
    transports: tuple[Transport, ...] | None = None
    divergence: Divergence | None = None
    deferred: str | None = None
    issue: str | None = None
    note: str | None = None
    added_in: SpecVersion | None = None
    removed_in: SpecVersion | None = None
    supersedes: tuple[str, ...] = ()
    superseded_by: str | None = None
    arm_exclusions: tuple[ArmExclusion, ...] = ()
    known_failures: tuple[KnownFailure, ...] = ()

    def __post_init__(self) -> None:
        if not _SOURCE_PATTERN.fullmatch(self.source):
            raise ValueError(f"source must be a specification URL, 'sdk', or 'issue:#n', got {self.source!r}")
        if self.added_in is not None and self.added_in not in KNOWN_PROTOCOL_VERSIONS:
            raise ValueError(f"added_in {self.added_in!r} is not in KNOWN_PROTOCOL_VERSIONS")
        if self.removed_in is not None and self.removed_in not in KNOWN_PROTOCOL_VERSIONS:
            raise ValueError(f"removed_in {self.removed_in!r} is not in KNOWN_PROTOCOL_VERSIONS")
        if (
            self.added_in is not None
            and self.removed_in is not None
            and KNOWN_PROTOCOL_VERSIONS.index(self.added_in) >= KNOWN_PROTOCOL_VERSIONS.index(self.removed_in)
        ):
            raise ValueError(f"added_in {self.added_in!r} must be earlier than removed_in {self.removed_in!r}")


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
        removed_in="2026-07-28",
        note="initialize handshake removed at 2026-07-28; per-request _meta envelope replaces it.",
    ),
    "lifecycle:initialize:server-info": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#initialization",
        behavior="The initialize result identifies the server: name and version, plus title when declared.",
        removed_in="2026-07-28",
        superseded_by="lifecycle:discover:basic",
        note="initialize handshake removed at 2026-07-28; server identity moved to the server/discover result.",
    ),
    "lifecycle:initialize:instructions": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#initialization",
        behavior="A server may include an instructions string in the initialize result; the client exposes it.",
        removed_in="2026-07-28",
        superseded_by="lifecycle:discover:instructions",
        note="initialize handshake removed at 2026-07-28; instructions moved to the server/discover result.",
    ),
    "lifecycle:initialize:capabilities:from-handlers": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#capability-negotiation",
        behavior=(
            "The server advertises a capability for each feature area it has a registered handler for, "
            "and omits the capability for areas it does not."
        ),
        removed_in="2026-07-28",
        superseded_by="lifecycle:discover:capabilities:from-handlers",
        note=(
            "initialize handshake removed at 2026-07-28; server capability advertisement moved to the "
            "server/discover result."
        ),
    ),
    "lifecycle:initialize:capabilities:minimal": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#capability-negotiation",
        behavior="A server with no feature handlers advertises no feature capabilities.",
        removed_in="2026-07-28",
        superseded_by="lifecycle:discover:capabilities:from-handlers",
        note=(
            "initialize handshake removed at 2026-07-28; server capability advertisement moved to the "
            "server/discover result."
        ),
    ),
    "lifecycle:initialize:client-info": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#initialization",
        behavior="The client's name, version, and title are visible to server handlers after initialization.",
        removed_in="2026-07-28",
        superseded_by="lifecycle:envelope:stamped-on-every-request",
        note="initialize handshake removed at 2026-07-28; per-request _meta envelope replaces it.",
        arm_exclusions=(ArmExclusion(reason="requires-session", transport="streamable-http-stateless"),),
    ),
    "lifecycle:initialize:client-capabilities": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#capability-negotiation",
        behavior=(
            "The client capabilities visible to the server reflect which client callbacks are configured "
            "(sampling, elicitation, roots)."
        ),
        removed_in="2026-07-28",
        superseded_by="lifecycle:envelope:stamped-on-every-request",
        note="initialize handshake removed at 2026-07-28; per-request _meta envelope replaces it.",
        arm_exclusions=(ArmExclusion(reason="requires-session", transport="streamable-http-stateless"),),
    ),
    "lifecycle:initialized-notification": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#initialization",
        behavior=(
            "After successful initialization, the client sends exactly one initialized notification, "
            "before any non-ping request."
        ),
        removed_in="2026-07-28",
        note="initialize handshake removed at 2026-07-28; per-request _meta envelope replaces it.",
    ),
    "lifecycle:ping": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/ping#behavior-requirements",
        behavior="ping in either direction returns an empty result.",
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); ping deleted from the schema, no replacement.",
    ),
    "ping:client-to-server": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/ping#behavior-requirements",
        behavior="A client-initiated ping receives an empty result from the server.",
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); ping deleted from the schema, no replacement.",
    ),
    "ping:server-to-client": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/ping#behavior-requirements",
        behavior="A server-initiated ping receives an empty result from the client.",
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); ping deleted from the schema, no replacement.",
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "lifecycle:requests-before-initialized": Requirement(
        source="sdk",
        behavior=(
            "A request other than ping sent before the initialization handshake completes is rejected with an error."
        ),
        removed_in="2026-07-28",
        note="initialize handshake removed at 2026-07-28; per-request _meta envelope replaces it.",
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
        removed_in="2026-07-28",
        superseded_by="lifecycle:discover:retry-on-32022",
        note="initialize-time version negotiation removed at 2026-07-28; version carried per-request in _meta.",
    ),
    "lifecycle:version:match": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#version-negotiation",
        behavior=(
            "When the server supports the requested protocol version it echoes that version in the "
            "initialize result, and the connection proceeds at that version."
        ),
        removed_in="2026-07-28",
        note="initialize-time version negotiation removed at 2026-07-28; version carried per-request in _meta.",
    ),
    "lifecycle:version:server-fallback-latest": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#version-negotiation",
        behavior=(
            "An initialize request carrying a protocol version the server does not support is answered "
            "with another version the server supports — the latest one — rather than an error."
        ),
        removed_in="2026-07-28",
        superseded_by="lifecycle:version:unsupported-32022",
        note="initialize-time version negotiation removed at 2026-07-28; version carried per-request in _meta.",
    ),
    "lifecycle:version:reject-unsupported": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#version-negotiation",
        behavior=(
            "A client that receives an initialize response carrying a protocol version it does not "
            "support fails initialization with an error rather than proceeding with the session."
        ),
        removed_in="2026-07-28",
        superseded_by="lifecycle:discover:retry-on-32022",
        note="initialize-time version negotiation removed at 2026-07-28; version carried per-request in _meta.",
    ),
    "lifecycle:stateless:request-envelope": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic#_meta",
        behavior=(
            "At protocol_version 2026-07-28, every request carries io.modelcontextprotocol/protocolVersion, "
            "/clientInfo, and /clientCapabilities in params._meta; no initialize handshake occurs."
        ),
        added_in="2026-07-28",
    ),
    "lifecycle:stateless:caller-meta-preserved": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic#_meta",
        behavior=(
            "Caller-supplied _meta keys on a request survive the per-request envelope merge: the "
            "three io.modelcontextprotocol/* envelope keys overwrite any caller-supplied values for "
            "those keys; non-colliding caller keys are preserved."
        ),
        added_in="2026-07-28",
    ),
    "lifecycle:stateless:unpinned-legacy-wire": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/versioning",
        behavior=(
            "An unpinned session that negotiates an earlier protocol version emits no 2026-07-28 "
            "vocabulary on any JSON-RPC frame in either direction."
        ),
        deferred=(
            "bare-ClientSession seam; the high-level Client + HTTP-seam scan in "
            "hosting:http:legacy-no-modern-vocabulary covers the same vocabulary set"
        ),
    ),
    "lifecycle:envelope:stamped-on-every-request": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic#_meta",
        behavior=(
            "Every client→server request on a modern-negotiated session carries "
            "_meta.{protocolVersion,clientInfo,clientCapabilities}."
        ),
        added_in="2026-07-28",
        supersedes=(
            "lifecycle:initialize:client-info",
            "lifecycle:initialize:client-capabilities",
            "sampling:capability:declare",
        ),
        note=(
            "The spec MUST covers requests only. The session's modern stamp is message-agnostic, so "
            "session-sent notifications carry the envelope too, while dispatcher-built frames (the "
            "courtesy cancel) do not; neither notification arm is asserted here."
        ),
    ),
    "lifecycle:envelope:header-matches-meta": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#protocol-version-header",
        behavior="On HTTP, the MCP-Protocol-Version header on every POST matches _meta.protocolVersion in the body.",
        transports=("streamable-http", "streamable-http-stateless"),
        added_in="2026-07-28",
        note="HTTP-only: the header is a streamable-http transport concern; stdio and in-memory carry no headers.",
    ),
    "lifecycle:discover:basic": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/discover",
        behavior=(
            "Calling discover() sends server/discover with no params and returns a typed DiscoverResult "
            "carrying supportedVersions, capabilities and serverInfo."
        ),
        added_in="2026-07-28",
        supersedes=("lifecycle:initialize:server-info",),
    ),
    "lifecycle:discover:retry-on-32022": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/versioning#protocol-version-negotiation",
        behavior=(
            "When server/discover returns -32022 UnsupportedProtocolVersion, the client retries once with "
            "the intersection of error.data.supported and its own modern versions; an empty intersection raises."
        ),
        added_in="2026-07-28",
        supersedes=("lifecycle:version:downgrade", "lifecycle:version:reject-unsupported"),
    ),
    "lifecycle:discover:instructions": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/discover#discoverresult",
        behavior=(
            "A server-configured instructions string is returned in the server/discover result and exposed "
            "to the client."
        ),
        added_in="2026-07-28",
        supersedes=("lifecycle:initialize:instructions",),
    ),
    "lifecycle:discover:capabilities:from-handlers": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/discover#response",
        behavior=(
            "The capabilities object in the server/discover result advertises a capability for each feature "
            "area with a registered handler and omits feature areas without one."
        ),
        added_in="2026-07-28",
        supersedes=(
            "lifecycle:initialize:capabilities:from-handlers",
            "lifecycle:initialize:capabilities:minimal",
            "tools:capability:declared",
            "resources:capability:declared",
            "prompts:capability:declared",
            "completion:capability:declared",
            "logging:capability:declared",
            "mcpserver:completion:capability-auto",
        ),
    ),
    "lifecycle:discover:era-cached": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/versioning#backward-compatibility-with-initialization-based-versions",
        behavior=(
            "An auto-negotiating client probes server/discover exactly once per connection and "
            "reuses the adopted result for every subsequent request; an explicit discover() "
            "returns the cached result with no new wire traffic."
        ),
        added_in="2026-07-28",
        note=(
            "A SHOULD: cache the era verdict for the lifetime of the server process (stdio) or "
            "origin (HTTP). The SDK's cache is the session's adopted DiscoverResult, so the "
            "pinned lifetime is the connection. The MAY-persist-across-restarts clause is "
            "carried by lifecycle:mode:prior-discover-zero-rtt; the re-probe-on-stale follow-on "
            "is lifecycle:mode:prior-discover-stale-reprobe (deferred)."
        ),
    ),
    "lifecycle:version:unsupported-32022": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/versioning#protocol-version-negotiation",
        behavior=(
            "A request declaring a protocol version the server does not implement is answered with -32022 "
            "UnsupportedProtocolVersionError whose data.supported lists the versions the server does support."
        ),
        added_in="2026-07-28",
        supersedes=("lifecycle:version:server-fallback-latest",),
        note=(
            "Only the unknown-version half of the MUST is constructible: the server's "
            "supported-version set has no public knob (the modern entry always passes the "
            "MODERN_PROTOCOL_VERSIONS default, a singleton at this pin), so a server that "
            "declines a known version cannot be built."
        ),
    ),
    "lifecycle:version:era-method-gate": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/versioning",
        behavior=(
            "A request whose method exists at an earlier protocol revision but is removed at "
            "the negotiated 2026-07-28 era (e.g. resources/subscribe) is answered "
            "METHOD_NOT_FOUND even when a handler for it is registered."
        ),
        added_in="2026-07-28",
        note=(
            "No single spec sentence: the gate is the method-registry consequence of the 2026 "
            "removals (key absence in the per-version surface map is the gate). Transport-"
            "independent, pinned on both 2026 cells. Instances pinned elsewhere: "
            "hosting:http:modern:initialize-removed (initialize) and "
            "hosting:http:modern:removed-method-status-404 (ping + the HTTP status half). The "
            "same call's 2025 success arm is resources:subscribe (removed_in 2026-07-28). The "
            "NC's other two legs are not entries: capability stripping is not implemented in "
            "python -- the era-agnostic derivation can advertise capabilities for "
            "era-removed methods on a 2026 discover result (probed: logging, "
            "resources.subscribe), ruled era-agnostic and conformant (schema.ts keeps "
            "logging deprecated-but-valid and subscribe era-unqualified) and deliberately "
            "unpinned as capability-API-redesign territory (the runtime advertises "
            "resources.subscribe while the listen runtime does not exist) -- and a client-side "
            "typed local era error is a TS surface python does not have."
        ),
    ),
    "lifecycle:version:dual-era-precedence": Requirement(
        source="sdk",
        behavior=(
            "A request that is simultaneously a valid modern envelope-bearing frame and a "
            "legacy handshake method -- initialize carrying a full _meta envelope and modern "
            "headers -- is classified modern and answered METHOD_NOT_FOUND, never served as a "
            "handshake."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "Only observable over streamable HTTP: python's only dual-era serving entry is the "
            "session manager, which keys classification on the MCP-Protocol-Version header and "
            "the envelope ladder behind it. source='sdk' because the spec's dual-era-server "
            "bullets (basic/versioning, Compatibility Matrix) define each signal separately and "
            "never say which wins on a frame carrying both; TS implements the identical "
            "precedence (NC-dual-era-precedence -- the spec-prose ambiguity is an upstream "
            "issue candidate). The headerless half of the precedence is "
            "hosting:http:modern:legacy-fallthrough."
        ),
    ),
    "lifecycle:discover:fallback-method-not-found": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/stdio#backward-compatibility",
        behavior=(
            "When server/discover returns a JSON-RPC error that is not a recognized modern negotiation "
            "error (-32022 retries or raises instead; see lifecycle:discover:retry-on-32022), or a bare "
            "HTTP 4xx, an auto-negotiating client falls back to the legacy initialize handshake and the "
            "connection succeeds at a handshake-era version; the fallback is not keyed to specific codes "
            "(legacy servers reject the probe with various codes)."
        ),
        added_in="2026-07-28",
        note=(
            "The SDK keys its no-fallback carve-out to -32022 alone, while the spec's carve-out is any "
            "recognized modern JSON-RPC error (an open set); no test drives a modern-error probe "
            "rejection other than -32022. A handshake-bearing -32022 supported list is a second "
            "unpinned reading: the SDK initializes when the intersection is empty but supported names "
            "a handshake-era version, which the stdio no-initialize-fallback-on--32022 bullet reads "
            "as forbidding, while the spec's own -32022 example lists 2025-11-25 in supported -- left "
            "unpinned until the spec text settles which bullet wins."
        ),
    ),
    "lifecycle:discover:timeout-falls-back": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/stdio#backward-compatibility",
        behavior=(
            "When server/discover does not respond within a reasonable timeout, the "
            "auto-negotiating client treats the server as legacy and falls back to the "
            "initialize handshake."
        ),
        added_in="2026-07-28",
        deferred=(
            "Not yet covered here: the server/discover probe timeout is the module-level "
            "constant DISCOVER_TIMEOUT_SECONDS = 10.0 (src/mcp/client/session.py) with no "
            "public override -- send_discover ignores read_timeout_seconds -- so observing the "
            "silent-server timeout trigger end-to-end is real-time-bound and is deliberately "
            "excluded from this suite; the fallback arm it feeds (any non--32022 MCPError from "
            "the probe leads to initialize) is covered by "
            "lifecycle:discover:fallback-method-not-found in "
            "tests/interaction/lowlevel/test_client_connect.py and by tests/client/test_probe.py."
        ),
    ),
    "lifecycle:discover:network-error-raises": Requirement(
        source="sdk",
        behavior=(
            "A network/connection error during server/discover propagates to the caller without "
            "falling back to initialize; fallback is reserved for server rejections (see "
            "lifecycle:discover:fallback-method-not-found). An outage is never an era verdict."
        ),
        transports=("streamable-http", "streamable-http-stateless"),
        added_in="2026-07-28",
        note="HTTP-only: distinguishes transport-level failures from server-side rejection.",
    ),
    "lifecycle:mode:auto-probes-first": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/stdio#backward-compatibility",
        behavior=(
            "A dual-era (mode='auto') client sends server/discover before any other request, "
            "carrying its preferred modern version in the probe's _meta protocolVersion."
        ),
        added_in="2026-07-28",
        note=(
            "A SHOULD. The spec sentence lives on the stdio page but binds the client's "
            "connect-time ordering, which is transport-independent code; asserted at the "
            "in-process HTTP seam like the sibling stdio#backward-compatibility entries."
        ),
    ),
    "lifecycle:mode:legacy-never-probes": Requirement(
        source="sdk",
        behavior=(
            "A Client constructed with mode='legacy' sends initialize as its first request "
            "and never sends server/discover."
        ),
        added_in="2026-07-28",
    ),
    "lifecycle:mode:pin-never-handshakes": Requirement(
        source="sdk",
        behavior=(
            "A Client constructed with mode='2026-07-28' sends no initialize and no server/discover; its "
            "first wire request is the caller's first call, carrying the full _meta envelope."
        ),
        added_in="2026-07-28",
    ),
    "lifecycle:mode:modern-only-legacy-peer": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/versioning",
        behavior=(
            "A modern-only client (a version-pinned Client) probes server/discover first on "
            "stdio so a legacy peer fails deterministically, and surfaces an actionable era "
            "error to the user."
        ),
        added_in="2026-07-28",
        divergence=Divergence(
            note=(
                "The pinned client's contract is the opposite by design: it adopts a local "
                "DiscoverResult with zero connect-time wire traffic (pinned by "
                "lifecycle:mode:pin-never-handshakes), so the probe-first SHOULD cannot be "
                "satisfied and a legacy peer fails non-deterministically."
            ),
        ),
        deferred=(
            "Not implemented in the SDK: the modern-only client (Client mode='<modern version "
            "pin>') never sends server/discover -- Client.__aenter__ "
            "(src/mcp/client/client.py) adopts prior_discover or a locally synthesized "
            "DiscoverResult with zero connect-time wire traffic, and no public option makes a "
            "pinned client probe first, so the probe-first deterministic-failure behaviour "
            "against a legacy peer cannot be driven; the no-probe half is already pinned by "
            "lifecycle:mode:pin-never-handshakes."
        ),
    ),
    "lifecycle:mode:prior-discover-zero-rtt": Requirement(
        source="sdk",
        behavior=(
            "A Client constructed with prior_discover=<DiscoverResult> sends no negotiation traffic; "
            "server_info and capabilities are populated from the prior result."
        ),
        added_in="2026-07-28",
    ),
    "lifecycle:mode:prior-discover-stale-reprobe": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/versioning#backward-compatibility-with-initialization-based-versions",
        behavior=(
            "A client that persisted a prior DiscoverResult re-probes when the cached version "
            "assumption later fails, instead of surfacing the stale -32022 failure to the caller."
        ),
        added_in="2026-07-28",
        deferred=(
            "Not implemented in the SDK: the client has no re-probe path when a cached prior "
            "version assumption later fails. Client.__aenter__ with a version-pin mode adopts "
            "prior_discover (or a synthesized DiscoverResult) with zero wire traffic "
            "(src/mcp/client/client.py), and -32022 UNSUPPORTED_PROTOCOL_VERSION is handled "
            "only at connect-time probe (src/mcp/client/_probe.py; "
            "src/mcp/client/session.py) -- there is no handling on the regular send_request "
            "path, so a stale prior surfaces as MCPError(-32022) to the caller with no re-probe."
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
    "protocol:directionality:no-client-responses": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns",
        behavior=(
            "A 2026-07-28 wire trace contains no server-initiated JSON-RPC requests and no "
            "client-sent JSON-RPC responses: every client-to-server frame is a request and every "
            "server-to-client frame is a response, even across a multi-round-trip exchange that at "
            "2025-11-25 was a server-initiated request answered by the client."
        ),
        added_in="2026-07-28",
        note=(
            "Asserted at the streamable HTTP wire seam: the in-memory 2026 transport dispatches "
            "typed objects directly with no JSON-RPC framing, so it has no trace to inspect."
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
        note=(
            "At 2026-07-28 the cancellation wire act splits by transport: stdio still sends "
            "notifications/cancelled (a MUST), while streamable HTTP replaces it with closing the response "
            "stream. A single superseded_by cannot encode the split; the 2026 faces are pinned by "
            "protocol:cancel:stdio-sends-cancelled and protocol:cancel:http-stream-close when the "
            "cancellation add-batch lands them."
        ),
    ),
    "protocol:cancel:handler-abort-propagates": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/cancellation#behavior-requirements",
        behavior="On the receiving side, a cancellation notification stops the running request handler.",
        arm_exclusions=(
            ArmExclusion(reason="requires-session", transport="streamable-http-stateless"),
            ArmExclusion(
                reason="requires-session",
                spec_version="2026-07-28",
                note=(
                    "Client-initiated cancellation persists at 2026-07-28 but the SDK's modern path does not "
                    "handle notifications/cancelled yet. Re-admission target is the in-memory arm only: on "
                    "streamable HTTP the 2026 cancellation signal is closing the response stream, pinned "
                    "separately by hosting:http:modern:disconnect-cancels-handler."
                ),
            ),
        ),
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
                "request; both seats send an error response (code 0, 'Request cancelled') instead — the "
                "server for cancelled client requests, and the client for cancelled server-initiated "
                "requests — which is what unblocks the sender's pending call."
            ),
        ),
        arm_exclusions=(
            ArmExclusion(reason="requires-session", transport="streamable-http-stateless"),
            ArmExclusion(
                reason="requires-session",
                spec_version="2026-07-28",
                note=(
                    "Client-initiated cancellation persists at 2026-07-28 but the SDK's modern path does not "
                    "handle notifications/cancelled yet. Re-admission target is the in-memory arm only: on "
                    "streamable HTTP the 2026 cancellation signal is closing the response stream, pinned "
                    "separately by hosting:http:modern:disconnect-cancels-handler."
                ),
            ),
        ),
    ),
    "protocol:cancel:initialize-not-cancellable": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/cancellation#behavior-requirements",
        behavior="The client never sends notifications/cancelled for the initialize request.",
    ),
    "protocol:cancel:late-response-ignored": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/cancellation#behavior-requirements",
        behavior=(
            "A response that arrives after the sender issued notifications/cancelled is ignored; the "
            "request stays failed and no error is raised."
        ),
    ),
    "protocol:cancel:server-survives": Requirement(
        source="sdk",
        behavior="The session continues to serve new requests after an earlier request was cancelled.",
        arm_exclusions=(
            ArmExclusion(reason="requires-session", transport="streamable-http-stateless"),
            ArmExclusion(
                reason="requires-session",
                spec_version="2026-07-28",
                note=(
                    "Client-initiated cancellation persists at 2026-07-28 but the SDK's modern path does not "
                    "handle notifications/cancelled yet. Re-admission target is the in-memory arm only: on "
                    "streamable HTTP the 2026 cancellation signal is closing the response stream, pinned "
                    "separately by hosting:http:modern:disconnect-cancels-handler."
                ),
            ),
        ),
    ),
    "protocol:cancel:server-to-client": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/cancellation#behavior-requirements",
        behavior=(
            "A server that abandons an in-flight server-initiated request (sampling, elicitation, roots) "
            "cancels it, and the client stops processing the cancelled request."
        ),
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2322/SEP-2575); with server-initiated requests retired there is "
            "nothing in flight on the client for a server to cancel, and servers MUST NOT send "
            "notifications/cancelled except to tear down a subscriptions/listen stream (pinned separately as "
            "protocol:cancel:server-listen-only when the cancellation slice lands it). No replacement."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
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
    "protocol:error:handler-error-passthrough": Requirement(
        source="sdk",
        behavior=(
            "An MCPError raised by a request handler is returned to the caller as a JSON-RPC error "
            "carrying the handler-chosen code and message verbatim."
        ),
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
        arm_exclusions=(
            ArmExclusion(
                reason="modern-error-surface",
                spec_version="2026-07-28",
                note=(
                    "The modern entry maps Exception->INTERNAL_ERROR (-32603) with an opaque message, so the "
                    "2026 arm SATISFIES this requirement; the test pins the legacy code-0 divergence and "
                    "needs an era-aware assertion before re-admission."
                ),
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
    "protocol:error:null-id": Requirement(
        source="sdk",
        behavior=(
            "An error response carrying a null id — the JSON-RPC shape for a peer reporting a failure it "
            "could not attribute to a request, such as a parse error — is surfaced to the application "
            "rather than silently discarded."
        ),
        divergence=Divergence(
            note=(
                "The dispatcher drops null-id error responses with a debug log; in v1, JSONRPCError.id was "
                "non-nullable, so a null-id error response failed transport validation and the resulting "
                "ValidationError was surfaced to message_handler as an exception. The v2 fault channel "
                "exists (message_handler receives stream exceptions), but response routing drops the "
                "null-id error before anything reaches it."
            ),
        ),
        deferred=(
            "Not yet covered here: the current drop is pinned at the dispatcher level by "
            "tests/shared/test_jsonrpc_dispatcher.py; an interaction-level test waits on the dispatcher "
            "routing null-id errors into the existing fault channel."
        ),
    ),
    "protocol:meta:related-task": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#related-task-metadata",
        behavior="Messages may carry related-task _meta associating them with a task.",
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    "protocol:meta:request-to-handler": Requirement(
        source=f"{SPEC_BASE_URL}/basic#_meta",
        behavior="The _meta object the client attaches to a request is visible to the server handler.",
        arm_exclusions=(
            ArmExclusion(
                reason="legacy-only-vocabulary",
                spec_version="2026-07-28",
                note=(
                    "The pass-through itself holds at 2026, but the modern envelope merges the reserved "
                    "io.modelcontextprotocol/* keys into every request's _meta, so the test's "
                    "nothing-else-injected equality assertion only holds on the legacy wire; needs an "
                    "era-aware assertion before re-admission."
                ),
            ),
        ),
    ),
    "protocol:meta:result-to-client": Requirement(
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
        arm_exclusions=(ArmExclusion(reason="asserts-legacy-handshake", spec_version="2026-07-28"),),
    ),
    "protocol:progress:token-unique": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/progress#progress-flow",
        behavior=("Concurrent in-flight requests that each supply a progress callback carry distinct progress tokens."),
        note=(
            "Tested as the consequence: each callback receives only its own request's progress under "
            "interleaved emission. Token distinctness is the JSON-RPC mechanism for that; the in-process "
            "direct dispatcher carries the callback per-request without a wire-level token."
        ),
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
        arm_exclusions=(
            ArmExclusion(reason="requires-session", transport="streamable-http-stateless"),
            ArmExclusion(reason="requires-session", spec_version="2026-07-28"),
        ),
    ),
    "protocol:progress:late-dropped-by-client": Requirement(
        source="sdk",
        behavior=(
            "A progress notification that arrives after its request has completed is not delivered to the "
            "original progress callback."
        ),
        arm_exclusions=(
            ArmExclusion(reason="requires-session", transport="streamable-http-stateless"),
            ArmExclusion(reason="requires-session", spec_version="2026-07-28"),
        ),
    ),
    "protocol:progress:no-token": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/progress#progress-flow",
        behavior="Without a progress callback the request carries no progress token.",
    ),
    "protocol:progress:client-to-server": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/progress#progress-flow",
        behavior="A progress notification sent by the client is delivered to the server's progress handler.",
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2575); client-to-server progress is unrepresentable -- the only "
            "client notification is notifications/cancelled, and there are no server-initiated requests to "
            "report progress on."
        ),
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
        note=(
            "At 2026-07-28 on streamable HTTP, timeout cancellation is expressed by closing the response "
            "stream rather than notifications/cancelled; the in-memory act this entry pins remains "
            "spec-correct. Era-unbounded by design."
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
        removed_in="2026-07-28",
        superseded_by="mrtr:tools-call:write-once-roundtrip",
        note=(
            "removed in 2026-07-28 (SEP-2322); the in-tool elicitation round trip is now the MRTR "
            "input_required/retry loop."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "tools:call:is-error": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#error-handling",
        behavior=(
            "A tool execution failure is returned as a result with isError true and the failure described "
            "in content, not as a JSON-RPC error."
        ),
    ),
    "tools:call:logging-mid-execution": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/logging#log-message-notifications",
        behavior=(
            "Log notifications emitted by a tool handler during execution reach the client's logging "
            "callback before the tool result returns."
        ),
        divergence=Divergence(
            note=(
                "At 2026-07-28 the spec forbids notifications/message for a request whose _meta lacks the "
                "io.modelcontextprotocol/logLevel opt-in; the session's send_log_message never reads that "
                "key and the tool handler's mid-call messages are delivered unconditionally, so a bound "
                "test pins the un-gated delivery on the live 2026-07-28 cells."
            ),
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
        removed_in="2026-07-28",
        superseded_by="sampling:mrtr:create:basic",
        note=(
            "removed in 2026-07-28 (SEP-2322); the in-tool sampling round trip is now the MRTR "
            "input_required/retry loop."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "tools:call:structured-content": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#structured-content",
        behavior="A tool result can carry structuredContent alongside content; the client receives both.",
    ),
    "tools:call:structured-content:text-mirror": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#structured-content",
        behavior="A tool returning structured content also returns the serialized JSON as a text content block.",
        divergence=Divergence(
            note=(
                "Holds for object returns (the bound test pins the serialized-JSON mirror); a "
                "list-returning tool yields one text block per element rather than the serialized JSON "
                "of its structured value (pinned by the test on mcpserver:tool:output-schema:wrapped)."
            ),
        ),
    ),
    "tools:call:unknown-name": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#error-handling",
        behavior="tools/call for a name the server does not recognise returns a JSON-RPC error.",
    ),
    "tools:capability:declared": Requirement(
        source=f"{SPEC_BASE_URL}/server/tools#capabilities",
        behavior="A server with a list_tools handler advertises the tools capability in its initialize result.",
        removed_in="2026-07-28",
        superseded_by="lifecycle:discover:capabilities:from-handlers",
        note=(
            "initialize handshake removed at 2026-07-28; server capability advertisement moved to the "
            "server/discover result."
        ),
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
        removed_in="2026-07-28",
        superseded_by="tools:listen:list-changed",
        note=(
            "removed in 2026-07-28 (SEP-2575); unsolicited server notifications retired -- list_changed is "
            "delivered only on a subscriptions/listen stream."
        ),
        arm_exclusions=(ArmExclusion(reason="requires-session", transport="streamable-http-stateless"),),
    ),
    "tools:listen:list-changed": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/tools#list-changed-notification",
        behavior=(
            "A notifications/tools/list_changed emitted while a client's subscriptions/listen stream "
            "requested toolsListChanged is delivered on that stream and dispatched to the client's "
            "registered notification handler."
        ),
        added_in="2026-07-28",
        supersedes=("tools:list-changed",),
        deferred=(
            "Not implemented in the SDK: subscriptions/listen has wire types and a lowlevel handler hook, "
            "but no runtime -- there is no client-side listen API, and no server machinery emits the "
            "acknowledgment, narrows the filter, or routes notifications onto a listen stream."
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
    "client:x-mcp-header:invalid-definition-rejected": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#schema-extension",
        behavior=(
            "A tool definition whose x-mcp-header value violates the schema-extension "
            "constraints is rejected by the modern client: the tool is excluded from the "
            "tools/list result while valid sibling tools survive."
        ),
        added_in="2026-07-28",
        note=(
            "The spec scopes the rejection MUST to clients using the Streamable HTTP transport "
            "(other transports MAY ignore the annotations); the SDK gates on the negotiated modern "
            "version instead, so the exclusion also runs on the in-memory 2026 connection -- a "
            "deliberate superset, pinned on both cells."
        ),
    ),
    "client:x-mcp-header:invalid-definition-rejected:empty": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#schema-extension",
        behavior=(
            "A tool whose x-mcp-header annotation is the empty string is excluded from the "
            "modern client's tools/list result."
        ),
        added_in="2026-07-28",
        note=(
            "The spec scopes the rejection MUST to clients using the Streamable HTTP transport "
            "(other transports MAY ignore the annotations); the SDK gates on the negotiated modern "
            "version instead, so the exclusion also runs on the in-memory 2026 connection -- a "
            "deliberate superset, pinned on both cells."
        ),
    ),
    "client:x-mcp-header:invalid-definition-rejected:non-tchar": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#schema-extension",
        behavior=(
            "A tool whose x-mcp-header annotation is not an RFC 9110 field-name token is "
            "excluded from the modern client's tools/list result."
        ),
        added_in="2026-07-28",
        note=(
            "The spec scopes the rejection MUST to clients using the Streamable HTTP transport "
            "(other transports MAY ignore the annotations); the SDK gates on the negotiated modern "
            "version instead, so the exclusion also runs on the in-memory 2026 connection -- a "
            "deliberate superset, pinned on both cells."
        ),
    ),
    "client:x-mcp-header:invalid-definition-rejected:control-chars": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#schema-extension",
        behavior=(
            "A tool whose x-mcp-header annotation contains control characters (CR/LF) is "
            "excluded from the modern client's tools/list result."
        ),
        added_in="2026-07-28",
        note=(
            "The spec scopes the rejection MUST to clients using the Streamable HTTP transport "
            "(other transports MAY ignore the annotations); the SDK gates on the negotiated modern "
            "version instead, so the exclusion also runs on the in-memory 2026 connection -- a "
            "deliberate superset, pinned on both cells."
        ),
    ),
    "client:x-mcp-header:invalid-definition-rejected:duplicate": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#schema-extension",
        behavior=(
            "A tool whose inputSchema carries two x-mcp-header values equal under "
            "case-insensitive comparison is excluded from the modern client's tools/list result."
        ),
        added_in="2026-07-28",
        note=(
            "The spec scopes the rejection MUST to clients using the Streamable HTTP transport "
            "(other transports MAY ignore the annotations); the SDK gates on the negotiated modern "
            "version instead, so the exclusion also runs on the in-memory 2026 connection -- a "
            "deliberate superset, pinned on both cells."
        ),
    ),
    "client:x-mcp-header:invalid-definition-rejected:non-primitive": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#schema-extension",
        behavior=(
            "An x-mcp-header annotation on a non-primitive property (e.g. type number, which "
            "the spec explicitly forbids) makes the tool definition invalid and the modern "
            "client excludes it from tools/list."
        ),
        added_in="2026-07-28",
        note=(
            "The spec scopes the rejection MUST to clients using the Streamable HTTP transport "
            "(other transports MAY ignore the annotations); the SDK gates on the negotiated modern "
            "version instead, so the exclusion also runs on the in-memory 2026 connection -- a "
            "deliberate superset, pinned on both cells."
        ),
    ),
    "client:x-mcp-header:invalid-definition-rejected:not-statically-reachable": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#schema-extension",
        behavior=(
            "An x-mcp-header annotation on a property not reachable from the schema root via a "
            "pure properties chain (e.g. under items) invalidates the tool and the modern client "
            "excludes it from tools/list; an annotation on a nested pure-properties chain stays valid."
        ),
        added_in="2026-07-28",
        note=(
            "The spec scopes the rejection MUST to clients using the Streamable HTTP transport "
            "(other transports MAY ignore the annotations); the SDK gates on the negotiated modern "
            "version instead, so the exclusion also runs on the in-memory 2026 connection -- a "
            "deliberate superset, pinned on both cells."
        ),
    ),
    "client:x-mcp-header:invalid-tool-excluded:logs-warning": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/tools#x-mcp-header",
        behavior=(
            "When the modern client rejects a tool definition over an invalid x-mcp-header, "
            "it logs a warning naming the tool and the reason for rejection."
        ),
        added_in="2026-07-28",
        note="A SHOULD; the same text also appears on the streamable-http transport page.",
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
        arm_exclusions=(
            ArmExclusion(reason="requires-session", transport="streamable-http-stateless"),
            ArmExclusion(reason="asserts-legacy-handshake", spec_version="2026-07-28"),
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
        removed_in="2026-07-28",
        superseded_by="mrtr:url-elicitation:no-32042-on-2026",
        note=(
            "removed in 2026-07-28 (SEP-2322); error -32042 retired, replaced by an MRTR input_required result "
            "carrying inputRequests."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # MCPServer: Context helpers (SDK)
    # ═══════════════════════════════════════════════════════════════════════════
    "mcpserver:context:log-from-handler": Requirement(
        source="sdk",
        behavior=(
            "The Context logging helpers (debug/info/warning/error) send log message notifications at the "
            "corresponding severity."
        ),
        divergence=Divergence(
            note=(
                "At 2026-07-28 the spec forbids notifications/message for a request whose _meta lacks the "
                "io.modelcontextprotocol/logLevel opt-in; the Context helpers never read that key and emit "
                "unconditionally, so a bound test pins the un-gated delivery on the live 2026-07-28 cells."
            ),
        ),
    ),
    "mcpserver:context:progress": Requirement(
        source="sdk",
        behavior=(
            "Context.report_progress sends a progress notification against the requesting client's progress token."
        ),
    ),
    "mcpserver:context:elicit-from-handler": Requirement(
        source="sdk",
        behavior=(
            "Context.elicit sends a form elicitation built from a typed schema and returns a typed "
            "accepted/declined/cancelled result."
        ),
        removed_in="2026-07-28",
        superseded_by="mrtr:tools-call:write-once-roundtrip",
        note=(
            "removed in 2026-07-28 (SEP-2322); in-tool elicitation now returns an input_required result from "
            "the tool; the push Context API's 2026 failure mode is pinned separately by "
            "mrtr:push-api:loud-fail-2026."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
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
        removed_in="2026-07-28",
        superseded_by="lifecycle:discover:capabilities:from-handlers",
        note=(
            "initialize handshake removed at 2026-07-28; server capability advertisement moved to the "
            "server/discover result."
        ),
    ),
    "resources:list-changed": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#list-changed-notification",
        behavior=(
            "When the resource set changes, the server sends notifications/resources/list_changed and it "
            "reaches the client's handler."
        ),
        removed_in="2026-07-28",
        superseded_by="resources:listen:list-changed",
        note=(
            "removed in 2026-07-28 (SEP-2575); unsolicited server notifications retired -- list_changed is "
            "delivered only on a subscriptions/listen stream."
        ),
        arm_exclusions=(ArmExclusion(reason="requires-session", transport="streamable-http-stateless"),),
    ),
    "resources:listen:list-changed": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/resources#list-changed-notification",
        behavior=(
            "A notifications/resources/list_changed emitted while a client's subscriptions/listen stream "
            "requested resourcesListChanged is delivered on that stream and dispatched to the client's "
            "registered notification handler."
        ),
        added_in="2026-07-28",
        supersedes=("resources:list-changed",),
        deferred=(
            "Not implemented in the SDK: subscriptions/listen has wire types and a lowlevel handler hook, "
            "but no runtime -- there is no client-side listen API, and no server machinery emits the "
            "acknowledgment, narrows the filter, or routes notifications onto a listen stream."
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
    "resources:mrtr:read:basic": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/mrtr#supported-requests",
        behavior=(
            "A resources/read may be answered with an input_required result; the client fulfils the "
            "embedded request and the retried resources/read completes with the resource contents."
        ),
        added_in="2026-07-28",
        note=(
            "Low-level Server only: MCPServer returns InputRequiredResult from tools alone, so the "
            "resources/read MRTR leg has no mcpserver mirror."
        ),
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
        source=f"{SPEC_2026_BASE_URL}/server/resources#error-handling",
        behavior=(
            "resources/read for a URI matching no registered resource returns JSON-RPC error -32602 "
            "(invalid params) with the requested URI in error.data, per SEP-2164."
        ),
    ),
    "resources:subscribe": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#subscriptions",
        behavior="resources/subscribe delivers the URI to the server's subscribe handler and returns an empty result.",
        removed_in="2026-07-28",
        superseded_by="subscriptions:listen:ack-first-stamped",
        note="removed in 2026-07-28 (SEP-2575); resources/subscribe replaced by subscriptions/listen.",
    ),
    "resources:subscribe:capability-required": Requirement(
        source="sdk",
        behavior=(
            "resources/subscribe to a server that did not advertise the subscribe capability is rejected with an error."
        ),
        removed_in="2026-07-28",
        superseded_by="subscriptions:listen:honored-filter-narrows-to-advertised",
        note=(
            "removed in 2026-07-28 (SEP-2575); the resources/subscribe RPC is gone. The resources.subscribe "
            "capability flag is retained but reinterpreted as opt-in for the resourceSubscriptions filter on "
            "subscriptions/listen -- there is no separate subscriptions capability."
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
        removed_in="2026-07-28",
        superseded_by="resources:listen:updated",
        note="removed in 2026-07-28 (SEP-2575); resources/subscribe replaced by subscriptions/listen.",
    ),
    "subscriptions:listen:ack-first-stamped": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/subscriptions#acknowledgment",
        behavior=(
            "notifications/subscriptions/acknowledged is the first message on a subscriptions/listen stream "
            "and carries the listen request's JSON-RPC id verbatim under the io.modelcontextprotocol/subscriptionId "
            "_meta key, plus the honored subset of the requested filter."
        ),
        added_in="2026-07-28",
        supersedes=("resources:subscribe",),
        deferred=(
            "Not implemented in the SDK: subscriptions/listen has wire types and a lowlevel handler hook, "
            "but no runtime -- there is no client-side listen API, and no server machinery emits the "
            "acknowledgment, narrows the filter, or routes notifications onto a listen stream."
        ),
    ),
    "subscriptions:listen:honored-filter-narrows-to-advertised": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/subscriptions#acknowledgment",
        behavior=(
            "The acknowledged filter on a subscriptions/listen stream is the requested set narrowed to what "
            "the server supports -- a requested notification type the server does not advertise is omitted "
            "from the honored filter and never delivered."
        ),
        added_in="2026-07-28",
        supersedes=("resources:subscribe:capability-required",),
        deferred=(
            "Not implemented in the SDK: subscriptions/listen has wire types and a lowlevel handler hook, "
            "but no runtime -- there is no client-side listen API, and no server machinery emits the "
            "acknowledgment, narrows the filter, or routes notifications onto a listen stream."
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
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); resources/unsubscribe replaced by subscriptions/listen.",
    ),
    "resources:unsubscribe:stops-updates": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#subscriptions",
        behavior="After resources/unsubscribe the server stops sending updated notifications for that URI.",
        deferred=(
            "Not implemented in the SDK: the server keeps no subscription state, so whether updated "
            "notifications stop after unsubscribe is entirely handler code; there is no SDK behaviour to "
            "pin beyond the unsubscribe request reaching the handler (covered by resources:unsubscribe)."
        ),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); resources/unsubscribe replaced by subscriptions/listen.",
    ),
    "resources:updated-notification": Requirement(
        source=f"{SPEC_BASE_URL}/server/resources#subscriptions",
        behavior=(
            "A resources/updated notification sent by the server reaches the client carrying the URI of "
            "the changed resource."
        ),
        removed_in="2026-07-28",
        superseded_by="resources:listen:updated",
        note=(
            "removed in 2026-07-28 (SEP-2575); resources/updated is delivered only on a subscriptions/listen "
            "stream whose resourceSubscriptions filter names the URI."
        ),
        arm_exclusions=(ArmExclusion(reason="requires-session", transport="streamable-http-stateless"),),
    ),
    "resources:listen:updated": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/subscriptions#notification-filter",
        behavior=(
            "A notifications/resources/updated for a URI named in a subscriptions/listen request's "
            "resourceSubscriptions filter is delivered on that stream, carrying the changed URI and the "
            "io.modelcontextprotocol/subscriptionId stamp."
        ),
        added_in="2026-07-28",
        supersedes=("resources:subscribe:updated", "resources:updated-notification"),
        deferred=(
            "Not implemented in the SDK: subscriptions/listen has wire types and a lowlevel handler hook, "
            "but no runtime -- there is no client-side listen API, and no server machinery emits the "
            "acknowledgment, narrows the filter, or routes notifications onto a listen stream."
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
        behavior=(
            "A resource function that raises is surfaced to the caller as a JSON-RPC error response "
            "(-32603 Internal error), with the original exception text withheld."
        ),
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
    # ═══════════════════════════════════════════════════════════════════════════
    # Prompts
    # ═══════════════════════════════════════════════════════════════════════════
    "prompts:capability:declared": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#capabilities",
        behavior="A server with a list_prompts handler advertises the prompts capability in its initialize result.",
        removed_in="2026-07-28",
        superseded_by="lifecycle:discover:capabilities:from-handlers",
        note=(
            "initialize handshake removed at 2026-07-28; server capability advertisement moved to the "
            "server/discover result."
        ),
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
        arm_exclusions=(
            ArmExclusion(
                reason="modern-error-surface",
                spec_version="2026-07-28",
                note=(
                    "prompts/get persists at 2026-07-28; only the error surface differs. The test pins the "
                    "legacy code-0 error shape and needs an era-aware assertion before re-admission."
                ),
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
        removed_in="2026-07-28",
        superseded_by="prompts:listen:list-changed",
        note=(
            "removed in 2026-07-28 (SEP-2575); unsolicited server notifications retired -- list_changed is "
            "delivered only on a subscriptions/listen stream."
        ),
        arm_exclusions=(ArmExclusion(reason="requires-session", transport="streamable-http-stateless"),),
    ),
    "prompts:listen:list-changed": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/prompts#list-changed-notification",
        behavior=(
            "A notifications/prompts/list_changed emitted while a client's subscriptions/listen stream "
            "requested promptsListChanged is delivered on that stream and dispatched to the client's "
            "registered notification handler."
        ),
        added_in="2026-07-28",
        supersedes=("prompts:list-changed",),
        deferred=(
            "Not implemented in the SDK: subscriptions/listen has wire types and a lowlevel handler hook, "
            "but no runtime -- there is no client-side listen API, and no server machinery emits the "
            "acknowledgment, narrows the filter, or routes notifications onto a listen stream."
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
    "prompts:mrtr:get:basic": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/mrtr#supported-requests",
        behavior=(
            "A prompts/get may be answered with an input_required result; the client fulfils the "
            "embedded request and the retried prompts/get completes with the prompt messages."
        ),
        added_in="2026-07-28",
        note=(
            "Low-level Server only: MCPServer returns InputRequiredResult from tools alone, so the "
            "prompts/get MRTR leg has no mcpserver mirror."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Prompts: SDK guarantees
    # ═══════════════════════════════════════════════════════════════════════════
    "mcpserver:prompt:args-validation": Requirement(
        source=f"{SPEC_BASE_URL}/server/prompts#implementation-considerations",
        behavior="prompts/get arguments that fail the prompt's argument schema are rejected before the function runs.",
        arm_exclusions=(
            ArmExclusion(
                reason="modern-error-surface",
                spec_version="2026-07-28",
                note=(
                    "prompts/get persists at 2026-07-28; only the error surface differs. The test pins the "
                    "legacy code-0 error shape and needs an era-aware assertion before re-admission."
                ),
            ),
        ),
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
                "The spec SHOULD-lists -32602 Invalid params for an invalid prompt name; MCPServer raises "
                "ValueError, which the low-level server converts to error code 0."
            ),
        ),
        arm_exclusions=(
            ArmExclusion(
                reason="modern-error-surface",
                spec_version="2026-07-28",
                note=(
                    "prompts/get persists at 2026-07-28; only the error surface differs (legacy code 0 vs "
                    "-32602). The test pins the legacy shape and needs an era-aware assertion before "
                    "re-admission."
                ),
            ),
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Completion
    # ═══════════════════════════════════════════════════════════════════════════
    "completion:capability:declared": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/completion#capabilities",
        behavior="A server with a completion handler advertises the completions capability in its initialize result.",
        removed_in="2026-07-28",
        superseded_by="lifecycle:discover:capabilities:from-handlers",
        note=(
            "initialize handshake removed at 2026-07-28; server capability advertisement moved to the "
            "server/discover result."
        ),
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
        removed_in="2026-07-28",
        superseded_by="lifecycle:discover:capabilities:from-handlers",
        note=(
            "initialize handshake removed at 2026-07-28; server capability advertisement moved to the "
            "server/discover result."
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
        removed_in="2026-07-28",
        superseded_by="lifecycle:discover:capabilities:from-handlers",
        note=(
            "initialize handshake removed at 2026-07-28; server capability advertisement moved to the "
            "server/discover result."
        ),
    ),
    "logging:message:all-levels": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/logging#log-levels",
        behavior="All eight RFC 5424 severity levels are deliverable as log message notifications.",
        divergence=Divergence(
            note=(
                "At 2026-07-28 the spec forbids notifications/message for a request whose _meta lacks the "
                "io.modelcontextprotocol/logLevel opt-in; the session's send_log_message never reads that "
                "key and all eight severity levels are delivered unconditionally, so a bound test pins the "
                "un-gated delivery on the live 2026-07-28 cells."
            ),
        ),
    ),
    "logging:message:fields": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/logging#log-message-notifications",
        behavior=(
            "A log message sent by a server handler is delivered to the client's logging callback with its "
            "severity level, logger name, and data."
        ),
        divergence=Divergence(
            note=(
                "At 2026-07-28 the spec forbids notifications/message for a request whose _meta lacks the "
                "io.modelcontextprotocol/logLevel opt-in; the session's send_log_message never reads that "
                "key and the handler's messages are delivered unconditionally, so a bound test pins the "
                "un-gated delivery on the live 2026-07-28 cells."
            ),
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
        removed_in="2026-07-28",
        superseded_by="logging:per-request-level:opt-in",
        note=(
            "removed in 2026-07-28 (SEP-2575); logging/setLevel removed, replaced by per-request "
            "io.modelcontextprotocol/logLevel in _meta."
        ),
    ),
    "logging:set-level": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/logging#setting-log-level",
        behavior="logging/setLevel delivers the requested level to the server's handler and returns an empty result.",
        removed_in="2026-07-28",
        superseded_by="logging:per-request-level:opt-in",
        note=(
            "removed in 2026-07-28 (SEP-2575); logging/setLevel removed, replaced by per-request "
            "io.modelcontextprotocol/logLevel in _meta."
        ),
    ),
    "logging:set-level:invalid-level": Requirement(
        source=f"{SPEC_BASE_URL}/server/utilities/logging#error-handling",
        behavior="logging/setLevel with an invalid level value returns JSON-RPC error -32602 (Invalid params).",
        removed_in="2026-07-28",
        superseded_by="logging:per-request-level:invalid-level",
        note=(
            "removed in 2026-07-28 (SEP-2575); logging/setLevel removed, replaced by per-request "
            "io.modelcontextprotocol/logLevel in _meta."
        ),
    ),
    "logging:per-request-level:opt-in": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/logging#per-request-log-level",
        behavior=(
            "A request whose _meta carries io.modelcontextprotocol/logLevel receives notifications/message "
            "at or above that level on its own response stream, before the final response."
        ),
        added_in="2026-07-28",
        supersedes=("logging:set-level", "logging:message:filtered"),
        deferred=(
            "Not implemented in the SDK: the server never reads io.modelcontextprotocol/logLevel from a "
            "request's _meta -- the log helpers emit notifications/message unconditionally, with no "
            "suppression when the key is absent and no at-or-above-level filter on the request's own stream."
        ),
    ),
    "logging:per-request-level:invalid-level": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/logging#error-handling",
        behavior=(
            "A request carrying an unrecognized io.modelcontextprotocol/logLevel value is rejected with "
            "-32602 Invalid params."
        ),
        added_in="2026-07-28",
        supersedes=("logging:set-level:invalid-level",),
        deferred=(
            "Not implemented in the SDK: an unrecognized io.modelcontextprotocol/logLevel value is accepted "
            "rather than rejected with -32602; nothing validates the key on the inbound path."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Sampling (server → client)
    # ═══════════════════════════════════════════════════════════════════════════
    "sampling:capability:declare": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#capabilities",
        behavior=(
            "A client that handles sampling requests advertises the sampling capability in its initialize request."
        ),
        removed_in="2026-07-28",
        superseded_by="lifecycle:envelope:stamped-on-every-request",
        note=(
            "initialize handshake removed at 2026-07-28; client capabilities are stamped per-request in the "
            "_meta envelope."
        ),
        arm_exclusions=(ArmExclusion(reason="requires-session", transport="streamable-http-stateless"),),
    ),
    "sampling:create:basic": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#creating-messages",
        behavior=(
            "A sampling/createMessage request from a server handler is answered by the client's sampling "
            "callback, and the callback's result (role, content, model, stopReason) is returned to the handler."
        ),
        removed_in="2026-07-28",
        superseded_by="sampling:mrtr:create:basic",
        note=(
            "removed in 2026-07-28 (SEP-2322); server-initiated sampling/createMessage retired -- the "
            "request now rides MRTR inputRequests."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "sampling:create:include-context": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#capabilities",
        behavior="The includeContext value supplied by the server reaches the client callback intact.",
        removed_in="2026-07-28",
        superseded_by="sampling:mrtr:create:include-context",
        note=(
            "removed in 2026-07-28 (SEP-2322); server-initiated sampling/createMessage retired -- the "
            "request now rides MRTR inputRequests."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
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
        removed_in="2026-07-28",
        superseded_by="sampling:mrtr:capability:not-declared",
        note=(
            "removed in 2026-07-28 (SEP-2322); the push vehicle is retired -- the capability gate persists "
            "as the server-side embed gate on MRTR inputRequests."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "sampling:create:model-preferences": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#model-preferences",
        behavior=(
            "The model preferences supplied by the server (hints and the cost, speed, and intelligence "
            "priorities) reach the client callback intact."
        ),
        removed_in="2026-07-28",
        superseded_by="sampling:mrtr:create:model-preferences",
        note=(
            "removed in 2026-07-28 (SEP-2322); server-initiated sampling/createMessage retired -- the "
            "request now rides MRTR inputRequests."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "sampling:create:system-prompt": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#creating-messages",
        behavior="The system prompt supplied by the server reaches the client callback intact.",
        removed_in="2026-07-28",
        superseded_by="sampling:mrtr:create:system-prompt",
        note=(
            "removed in 2026-07-28 (SEP-2322); server-initiated sampling/createMessage retired -- the "
            "request now rides MRTR inputRequests."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
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
    "sampling:create:audio-content": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#audio-content",
        behavior="Sampling messages can carry audio content: base64 data with a mimeType.",
        removed_in="2026-07-28",
        superseded_by="sampling:mrtr:create:audio-content",
        note=(
            "removed in 2026-07-28 (SEP-2322); server-initiated sampling/createMessage retired -- the "
            "request now rides MRTR inputRequests."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "sampling:create:image-content": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#image-content",
        behavior="Sampling messages can carry image content: base64 data with a mimeType.",
        removed_in="2026-07-28",
        superseded_by="sampling:mrtr:create:image-content",
        note=(
            "removed in 2026-07-28 (SEP-2322); server-initiated sampling/createMessage retired -- the "
            "request now rides MRTR inputRequests."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "sampling:create:not-supported": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#capabilities",
        behavior=(
            "A sampling request to a client that did not declare the sampling capability fails with an "
            "error rather than hanging or being silently dropped; the spec names no error code for this case."
        ),
        removed_in="2026-07-28",
        superseded_by="sampling:mrtr:capability:not-declared",
        note=(
            "removed in 2026-07-28 (SEP-2322); the client no longer answers server requests -- the surviving "
            "protection is the server-side embed gate (and -32021 MissingRequiredClientCapability on the "
            "originating client request)."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "sampling:error:user-rejected": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#error-handling",
        behavior=(
            "A sampling request the user rejects is answered with a JSON-RPC error (the spec's code for "
            "this case is -1, 'User rejected sampling request'), surfaced to the requesting handler as an MCPError."
        ),
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2322); there is no error answer to a sampling request under MRTR -- "
            "the client simply does not retry and the server is not waiting. The -1 code dies with the "
            "answer plane. No replacement."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "sampling:message:content-cardinality": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling",
        behavior="A sampling message's content may be a single block or an array of blocks.",
        removed_in="2026-07-28",
        superseded_by="sampling:mrtr:message:content-cardinality",
        note=(
            "removed in 2026-07-28 (SEP-2322); server-initiated sampling/createMessage retired -- the "
            "request now rides MRTR inputRequests."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
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
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2322); the push answer this guarantee validated no longer exists. "
            "Whether the MRTR client driver enforces the same shape on fulfilment results is undesigned SDK "
            "surface -- re-pin as a new entry when it is."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
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
        removed_in="2026-07-28",
        superseded_by="sampling:mrtr:tool-result:no-mixed-content",
        note=(
            "removed in 2026-07-28 (SEP-2322); server-initiated sampling/createMessage retired -- the "
            "request now rides MRTR inputRequests."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
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
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2322); the push send this preflight guarded is retired. The "
            "tool-use/result balance MUST itself survives; an embedded-request preflight is undesigned SDK "
            "surface."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "sampling:tools:server-gated-by-capability": Requirement(
        source=f"{SPEC_BASE_URL}/client/sampling#tools-in-sampling",
        behavior=(
            "A tool-enabled sampling request to a client that did not declare sampling.tools is rejected "
            "by the server before anything reaches the wire (the SDK surfaces this as an Invalid params error)."
        ),
        removed_in="2026-07-28",
        superseded_by="sampling:mrtr:capability:not-declared",
        note=(
            "removed in 2026-07-28 (SEP-2322); the push vehicle is retired -- the capability gate persists "
            "as the server-side embed gate on MRTR inputRequests."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "sampling:mrtr:create:basic": Requirement(
        source=f"{SPEC_2026_BASE_URL}/client/sampling#creating-messages",
        behavior=(
            "An embedded sampling/createMessage request returned in an input_required result from a tool "
            "handler is fulfilled by the client's sampling callback, and the callback's result (role, "
            "content, model, stopReason) reaches the retried tool handler in inputResponses."
        ),
        added_in="2026-07-28",
        supersedes=("sampling:create:basic", "tools:call:sampling-roundtrip"),
    ),
    "sampling:mrtr:create:include-context": Requirement(
        source=f"{SPEC_2026_BASE_URL}/client/sampling#context-inclusion",
        behavior=(
            "The includeContext value supplied in an embedded sampling/createMessage request reaches the "
            "client sampling callback intact."
        ),
        added_in="2026-07-28",
        supersedes=("sampling:create:include-context",),
    ),
    "sampling:mrtr:create:model-preferences": Requirement(
        source=f"{SPEC_2026_BASE_URL}/client/sampling#model-preferences",
        behavior=(
            "The model preferences supplied in an embedded sampling/createMessage request (hints and the "
            "cost, speed, and intelligence priorities) reach the client sampling callback intact."
        ),
        added_in="2026-07-28",
        supersedes=("sampling:create:model-preferences",),
    ),
    "sampling:mrtr:create:system-prompt": Requirement(
        source=f"{SPEC_2026_BASE_URL}/client/sampling#system-prompt",
        behavior=(
            "The system prompt supplied in an embedded sampling/createMessage request reaches the client "
            "sampling callback intact."
        ),
        added_in="2026-07-28",
        supersedes=("sampling:create:system-prompt",),
    ),
    "sampling:mrtr:create:audio-content": Requirement(
        source=f"{SPEC_2026_BASE_URL}/client/sampling#audio-content",
        behavior=(
            "Messages in an embedded sampling/createMessage request can carry audio content (base64 data "
            "with a mimeType), reaching the client callback intact."
        ),
        added_in="2026-07-28",
        supersedes=("sampling:create:audio-content",),
        deferred=(
            "Not yet covered here: 2026-07-28 successor entry registered by the era pass ahead of its test; "
            "expected drivable by analogy with its triaged MRTR siblings."
        ),
    ),
    "sampling:mrtr:create:image-content": Requirement(
        source=f"{SPEC_2026_BASE_URL}/client/sampling#image-content",
        behavior=(
            "Messages in an embedded sampling/createMessage request can carry image content (base64 data "
            "with a mimeType), reaching the client callback intact."
        ),
        added_in="2026-07-28",
        supersedes=("sampling:create:image-content",),
        deferred=(
            "Not yet covered here: 2026-07-28 successor entry registered by the era pass ahead of its test; "
            "expected drivable by analogy with its triaged MRTR siblings."
        ),
    ),
    "sampling:mrtr:message:content-cardinality": Requirement(
        source=f"{SPEC_2026_BASE_URL}/client/sampling#messages",
        behavior=(
            "A message in an embedded sampling/createMessage request may carry a single content block or an "
            "array of blocks."
        ),
        added_in="2026-07-28",
        supersedes=("sampling:message:content-cardinality",),
        deferred=(
            "Not yet covered here: 2026-07-28 successor entry registered by the era pass ahead of its test; "
            "expected drivable by analogy with its triaged MRTR siblings."
        ),
    ),
    "sampling:mrtr:tool-result:no-mixed-content": Requirement(
        source=f"{SPEC_2026_BASE_URL}/client/sampling#tool-result-messages",
        behavior=(
            "A user message carrying tool_result content in an embedded sampling request contains only "
            "tool_result blocks; mixing tool_result with text, image, or audio content is rejected as invalid."
        ),
        added_in="2026-07-28",
        supersedes=("sampling:tool-result:no-mixed-content",),
        deferred=(
            "Not yet covered here: 2026-07-28 successor entry registered by the era pass ahead of its test; "
            "expected drivable by analogy with its triaged MRTR siblings."
        ),
    ),
    "sampling:mrtr:capability:not-declared": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/mrtr#server-requirements-basic-workflow",
        behavior=(
            "The server does not place a sampling/createMessage request in an input_required result's "
            "inputRequests for a client whose declared capabilities do not support it (tool-enabled "
            "requests require sampling.tools; thisServer/allServers context -- itself deprecated -- should "
            "not be used without sampling.context)."
        ),
        divergence=Divergence(
            note=(
                "The embed gate is not implemented: an input_required result carrying a "
                "sampling/createMessage request for a client that declared no sampling capability is "
                "transmitted as-is, and the violation surfaces as the client driver's refusal "
                "(INVALID_REQUEST, 'Sampling not supported') aborting the call. The sub-capability legs "
                "(sampling.tools, sampling.context) are equally ungated and covered by this divergence "
                "without separate pins."
            ),
            issue="L109",
        ),
        added_in="2026-07-28",
        supersedes=(
            "sampling:create:not-supported",
            "sampling:tools:server-gated-by-capability",
            "sampling:context:server-gated-by-capability",
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
        removed_in="2026-07-28",
        superseded_by="elicitation:mrtr:capability:not-declared",
        note=(
            "removed in 2026-07-28 (SEP-2322); the push vehicle is retired -- the mode-level gate persists "
            "as the server-side embed gate on MRTR inputRequests."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "elicitation:form:action:accept": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#response-actions",
        behavior=(
            "A form-mode elicitation answered with action 'accept' returns the user's content to the "
            "requesting handler."
        ),
        removed_in="2026-07-28",
        superseded_by="elicitation:mrtr:form:basic",
        note="removed in 2026-07-28 (SEP-2322); elicitation/create now rides MRTR inputRequests.",
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "elicitation:form:action:cancel": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#response-actions",
        behavior="A form-mode elicitation answered with action 'cancel' returns no content to the handler.",
        removed_in="2026-07-28",
        superseded_by="elicitation:mrtr:form:action:cancel",
        note="removed in 2026-07-28 (SEP-2322); elicitation/create now rides MRTR inputRequests.",
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "elicitation:form:action:decline": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#response-actions",
        behavior="A form-mode elicitation answered with action 'decline' returns no content to the handler.",
        removed_in="2026-07-28",
        superseded_by="elicitation:mrtr:form:action:decline",
        note="removed in 2026-07-28 (SEP-2322); elicitation/create now rides MRTR inputRequests.",
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "elicitation:form:basic": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#form-mode-elicitation-requests",
        behavior=(
            "A form-mode elicitation delivers the message and requested schema to the client callback "
            "exactly as the server sent them."
        ),
        removed_in="2026-07-28",
        superseded_by="elicitation:mrtr:form:basic",
        note="removed in 2026-07-28 (SEP-2322); elicitation/create now rides MRTR inputRequests.",
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
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
        removed_in="2026-07-28",
        superseded_by="elicitation:mrtr:capability:not-declared",
        note=(
            "removed in 2026-07-28 (SEP-2322); the client no longer answers elicitation requests (the "
            "-32602 answer plane is gone) -- the surviving protection is the server-side embed gate."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "elicitation:form:schema:enum-variants": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#requested-schema",
        behavior=(
            "Requested-schema enum fields (including titled and multi-select variants) reach the client "
            "callback as sent."
        ),
        removed_in="2026-07-28",
        superseded_by="elicitation:mrtr:form:schema:enum-variants",
        note="removed in 2026-07-28 (SEP-2322); elicitation/create now rides MRTR inputRequests.",
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "elicitation:form:schema:primitives": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#requested-schema",
        behavior="Requested-schema fields may be string (with format), number or integer, or boolean.",
        removed_in="2026-07-28",
        superseded_by="elicitation:mrtr:form:schema:primitives",
        note="removed in 2026-07-28 (SEP-2322); elicitation/create now rides MRTR inputRequests.",
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
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
                "elicit_with_validation helper enforces primitive-only fields before generating the schema). "
                "ClientSession likewise does not enforce it: the inbound surface gate is relaxed for "
                "requestedSchema.properties so older servers that emit anyOf for Optional fields still reach "
                "the elicitation callback."
            ),
        ),
        removed_in="2026-07-28",
        superseded_by="elicitation:mrtr:form:schema:restricted-subset",
        note="removed in 2026-07-28 (SEP-2322); elicitation/create now rides MRTR inputRequests.",
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
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
        removed_in="2026-07-28",
        superseded_by="mrtr:input-responses:invalid-rejected",
        note=(
            "removed in 2026-07-28 (SEP-2322); the server-side validation half re-homes to the MRTR "
            "inputResponses contract; the client-side validate-before-sending half folds into the MRTR "
            "client driver's contract -- covered when that is pinned."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "elicitation:url:action:accept-no-content": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#response-actions",
        behavior=(
            "A URL-mode elicitation delivers the message, URL, and elicitationId to the client; an accept "
            "response carries no content (accept means the user agreed to visit the URL, not that the "
            "interaction completed)."
        ),
        removed_in="2026-07-28",
        superseded_by="elicitation:mrtr:url:action-no-content",
        note="removed in 2026-07-28 (SEP-2322); URL-mode elicitation/create now rides MRTR inputRequests.",
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "elicitation:url:action:cancel": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#response-actions",
        behavior="A URL-mode elicitation answered with cancel returns the action with no content.",
        removed_in="2026-07-28",
        superseded_by="elicitation:mrtr:url:action-no-content",
        note="removed in 2026-07-28 (SEP-2322); URL-mode elicitation/create now rides MRTR inputRequests.",
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "elicitation:url:action:decline": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#response-actions",
        behavior="A URL-mode elicitation answered with decline returns the action with no content.",
        removed_in="2026-07-28",
        superseded_by="elicitation:mrtr:url:action-no-content",
        note="removed in 2026-07-28 (SEP-2322); URL-mode elicitation/create now rides MRTR inputRequests.",
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "elicitation:url:basic": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#url-mode-elicitation-requests",
        behavior=(
            "A url-mode elicitation delivers the elicitation id and URL to the client callback exactly as "
            "the server sent them."
        ),
        removed_in="2026-07-28",
        superseded_by="mrtr:url-elicitation:no-32042-on-2026",
        note="removed in 2026-07-28 (SEP-2322); URL-mode elicitation/create now rides MRTR inputRequests.",
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "elicitation:url:complete-notification": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#completion-notifications-for-url-mode-elicitation",
        behavior=(
            "An elicitation/complete notification sent by the server after an out-of-band elicitation "
            "finishes reaches the client carrying the elicitationId."
        ),
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (spec PR #2891); notifications/elicitation/complete and elicitationId removed, no "
            "replacement (under MRTR the client learns completion by retrying)."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "elicitation:url:complete-unknown-ignored": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#completion-notifications-for-url-mode-elicitation",
        behavior=(
            "The client ignores an elicitation/complete notification referencing an unknown or "
            "already-completed elicitationId without error."
        ),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (spec PR #2891); notifications/elicitation/complete removed, no replacement.",
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
        removed_in="2026-07-28",
        superseded_by="mrtr:url-elicitation:no-32042-on-2026",
        note=(
            "removed in 2026-07-28 (SEP-2322); error -32042 retired, replaced by an MRTR input_required result "
            "carrying inputRequests."
        ),
    ),
    "elicitation:mrtr:form:basic": Requirement(
        source=f"{SPEC_2026_BASE_URL}/client/elicitation#form-mode-elicitation-requests",
        behavior=(
            "An embedded form-mode elicitation/create request in an input_required result delivers the "
            "message and requested schema to the client's elicitation callback exactly as sent, and an "
            "accept response carrying the user's content reaches the retried handler in inputResponses."
        ),
        added_in="2026-07-28",
        supersedes=(
            "elicitation:form:basic",
            "elicitation:form:action:accept",
            "transport:streamable-http:server-to-client",
        ),
    ),
    "elicitation:mrtr:form:action:cancel": Requirement(
        source=f"{SPEC_2026_BASE_URL}/client/elicitation#response-actions",
        behavior=(
            "An embedded form-mode elicitation answered with action 'cancel' reaches the retried handler "
            "in inputResponses with no content."
        ),
        added_in="2026-07-28",
        supersedes=("elicitation:form:action:cancel",),
    ),
    "elicitation:mrtr:form:action:decline": Requirement(
        source=f"{SPEC_2026_BASE_URL}/client/elicitation#response-actions",
        behavior=(
            "An embedded form-mode elicitation answered with action 'decline' reaches the retried handler "
            "in inputResponses with no content."
        ),
        added_in="2026-07-28",
        supersedes=("elicitation:form:action:decline",),
    ),
    "elicitation:mrtr:form:schema:primitives": Requirement(
        source=f"{SPEC_2026_BASE_URL}/client/elicitation#requested-schema",
        behavior=(
            "Requested-schema fields on an embedded form-mode elicitation may be string (with format), "
            "number or integer, or boolean; they reach the client callback intact."
        ),
        added_in="2026-07-28",
        supersedes=("elicitation:form:schema:primitives",),
    ),
    "elicitation:mrtr:form:schema:enum-variants": Requirement(
        source=f"{SPEC_2026_BASE_URL}/client/elicitation#requested-schema",
        behavior=(
            "Requested-schema enum fields (including titled and multi-select variants) on an embedded "
            "form-mode elicitation reach the client callback as sent."
        ),
        added_in="2026-07-28",
        supersedes=("elicitation:form:schema:enum-variants",),
        deferred=(
            "Not yet covered here: 2026-07-28 successor entry registered by the era pass ahead of its test; "
            "expected drivable by analogy with its triaged MRTR siblings."
        ),
    ),
    "elicitation:mrtr:form:schema:restricted-subset": Requirement(
        source=f"{SPEC_2026_BASE_URL}/client/elicitation#requested-schema",
        behavior=(
            "Form-mode requested schemas on embedded elicitations are flat objects with primitive-typed "
            "properties only; nested structures and arrays of objects are not used."
        ),
        added_in="2026-07-28",
        supersedes=("elicitation:form:schema:restricted-subset",),
        deferred=(
            "Not yet covered here: 2026-07-28 successor entry registered by the era pass ahead of its test; "
            "expected drivable by analogy with its triaged MRTR siblings."
        ),
    ),
    "elicitation:mrtr:capability:not-declared": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/mrtr#server-requirements-basic-workflow",
        behavior=(
            "The server does not place an elicitation/create request in an input_required result's "
            "inputRequests for a client whose declared capabilities do not support it (including "
            "mode-level support: form vs url)."
        ),
        divergence=Divergence(
            note=(
                "The server does not gate input_required input requests against the client's declared "
                "capabilities: an elicitation/create is embedded and sent as-is to a client whose request "
                "envelope declared no elicitation capability. The mode-level half of the same MUST NOT "
                "(form vs url) is equally ungated and additionally unpinned -- a configured elicitation "
                "callback always declares both modes, so a form-only client is unproducible through the "
                "public API."
            ),
            issue="L109",
        ),
        added_in="2026-07-28",
        supersedes=("elicitation:form:not-supported", "elicitation:capability:server-respects-mode"),
    ),
    "elicitation:mrtr:url:action-no-content": Requirement(
        source=f"{SPEC_2026_BASE_URL}/client/elicitation#response-actions",
        behavior=(
            "ElicitResult actions for an embedded URL-mode elicitation carry no content: accept means the "
            "user agreed to visit the URL, and cancel/decline reach the retried handler with the action "
            "and no content."
        ),
        added_in="2026-07-28",
        supersedes=(
            "elicitation:url:action:accept-no-content",
            "elicitation:url:action:cancel",
            "elicitation:url:action:decline",
        ),
        deferred=(
            "Not yet covered here: 2026-07-28 successor entry registered by the era pass ahead of its test; "
            "expected drivable by analogy with its triaged MRTR siblings."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # MRTR (multi-round-trip requests, 2026-07-28)
    # ═══════════════════════════════════════════════════════════════════════════
    "mrtr:input-required-result:at-least-one-of": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/mrtr#server-requirements-basic-workflow",
        behavior=(
            "An InputRequiredResult carries at least one of inputRequests or requestState; a "
            "handler-built violation fails at construction and surfaces to the client as a JSON-RPC "
            "error, never as a malformed interim result."
        ),
        added_in="2026-07-28",
        note=(
            "The at-least-one-of MUST is enforced by construction (mcp_types model validator). Both "
            "2026 dispatchers map the handler's ValidationError to the shared "
            "ErrorData(INVALID_PARAMS, 'Invalid request parameters', data='') shape "
            "(handler_exception_to_error_data); INTERNAL_ERROR is arguably the more apt code for a "
            "server-side construction bug, but the spec mandates no code for this failure."
        ),
    ),
    "mrtr:input-required-result:result-type-serialized": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/index#result-responses",
        behavior=(
            "The serialized interim frame carries resultType input_required explicitly; the "
            "discriminator is never elided on the wire."
        ),
        added_in="2026-07-28",
    ),
    "mrtr:input-responses:invalid-rejected": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/mrtr#error-handling",
        behavior=(
            "The server validates that a retry's inputResponses parse as a valid InputResponses object; "
            "a structurally malformed map is rejected with a JSON-RPC error before the handler runs."
        ),
        added_in="2026-07-28",
        supersedes=("elicitation:form:response-validation",),
        note=(
            "Elicited content is handed to the handler without requestedSchema re-validation; servers "
            "validate semantic constraints themselves (spec asks only for structural validation)."
        ),
    ),
    "mrtr:input-responses:key-correspondence": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/mrtr#inputresponses",
        behavior=(
            "A retry's inputResponses map is keyed by the originating inputRequests keys, each value "
            "the client's typed result for that key's request (e.g. ElicitResult, ListRootsResult)."
        ),
        added_in="2026-07-28",
    ),
    "mrtr:url-elicitation:no-32042-on-2026": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/mrtr",
        behavior=(
            "URL-mode elicitation rides the multi-round-trip flow at 2026-07-28: a handler embeds a "
            "URL-mode elicitation/create in an input_required result, the registered elicitation callback "
            "fulfils it, the retried call completes, and error -32042 never appears on the wire."
        ),
        added_in="2026-07-28",
        supersedes=(
            "elicitation:url:basic",
            "elicitation:url:required-error",
            "mcpserver:tool:url-elicitation-error",
            "flow:elicitation:url-required-then-retry",
        ),
    ),
    "mrtr:tools-call:write-once-roundtrip": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/mrtr#basic-workflow",
        behavior=(
            "A tool that returns an input_required result on a 2026-07-28 connection is fulfilled by the "
            "client driver: the registered callback answers the embedded request, and the original call is "
            "retried with a fresh request id, a byte-exact requestState echo, and the collected "
            "inputResponses, completing as a plain CallToolResult."
        ),
        added_in="2026-07-28",
        supersedes=("tools:call:elicitation-roundtrip", "mcpserver:context:elicit-from-handler"),
    ),
    "mrtr:request-state-only:retry": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/mrtr#client-requirements-basic-workflow",
        behavior=(
            "An InputRequiredResult carrying only requestState (no inputRequests) is retried by the "
            "client driver with no inputResponses and the requestState echoed verbatim."
        ),
        added_in="2026-07-28",
        note=(
            "The spec's 'MAY retry the original request immediately' is permission; the SDK paces "
            "state-only retries with an internal 50 ms exponential backoff as its chosen pacing."
        ),
    ),
    "mrtr:request-state:omitted-when-absent": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/mrtr#client-requirements-basic-workflow",
        behavior=(
            "When an InputRequiredResult carries no requestState field, the client does not include "
            "a requestState key in the serialized retry."
        ),
        added_in="2026-07-28",
    ),
    "mrtr:request-state:scoped-to-originating-request": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/mrtr#client-requirements-basic-workflow",
        behavior=(
            "inputRequests and requestState affect only the client's retry of the originating "
            "request; they never appear on any other request the client sends in parallel."
        ),
        added_in="2026-07-28",
    ),
    "mrtr:multi-round:complete": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/mrtr#server-requirements-basic-workflow",
        behavior=(
            "A server may answer the same request with input_required on multiple successive attempts; "
            "after two or more productive rounds the retried request completes normally."
        ),
        added_in="2026-07-28",
        supersedes=("flow:elicitation:multi-step-form",),
    ),
    "mrtr:rounds-cap": Requirement(
        source="sdk",
        behavior=(
            "Client.call_tool / get_prompt / read_resource bound the input_required retry loop at the "
            "configurable input_required_max_rounds; a server that keeps answering input_required past "
            "the cap raises InputRequiredRoundsExceededError carrying the configured cap."
        ),
        added_in="2026-07-28",
    ),
    "mrtr:push-api:loud-fail-2026": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/mrtr",
        behavior=(
            "The push-style server-to-client request APIs (ServerSession.elicit_form / elicit_url / "
            "create_message / list_roots) on a 2026-07-28 connection fail with a typed local error "
            "(NoBackChannelError, INVALID_REQUEST) before any request reaches the client; a handler "
            "can catch it and fall back, and the originating call still completes."
        ),
        divergence=Divergence(
            note=(
                "The prohibition is enforced by each transport's missing back-channel, not by an "
                "era gate on the send path, and the enforcement splits per transport and per leg. "
                "Standalone sends (no related_request_id) raise NoBackChannelError locally on both "
                "2026 transports because the per-request Connection has no outbound channel. "
                "Request-scoped sends (related_request_id=...) ride the per-request dispatch "
                "context, whose can_send_request the modern HTTP entry hard-codes to False but the "
                "in-memory direct-dispatcher pair leaves at its True default -- so in-memory the "
                "forbidden elicitation/create frame IS transmitted, and the failure comes back from "
                "the client's 2026 version gate (METHOD_NOT_FOUND) instead of arising locally. An "
                "era-aware gate on the send path would loud-fail both legs on every transport; when "
                "it lands, re-pin the request-scoped in-memory test to the local NoBackChannelError "
                "and delete this divergence."
            ),
            issue="L107",
        ),
        added_in="2026-07-28",
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Roots (server → client)
    # ═══════════════════════════════════════════════════════════════════════════
    "roots:list-changed": Requirement(
        source=f"{SPEC_BASE_URL}/client/roots#root-list-changes",
        behavior="A roots/list_changed notification sent by the client is delivered to the server's handler.",
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2575); notifications/roots/list_changed removed, no replacement (the stateless "
            "model carries no client→server change notifications)."
        ),
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
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); notifications/roots/list_changed removed, no replacement.",
    ),
    "roots:list:basic": Requirement(
        source=f"{SPEC_BASE_URL}/client/roots#listing-roots",
        behavior=(
            "A roots/list request from a server handler is answered by the client's roots callback, and "
            "the returned roots (uri, name) reach the handler."
        ),
        removed_in="2026-07-28",
        superseded_by="roots:mrtr:list:basic",
        note="removed in 2026-07-28 (SEP-2322); roots/list now rides MRTR inputRequests.",
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "roots:list:client-error": Requirement(
        source=f"{SPEC_BASE_URL}/client/roots#error-handling",
        behavior="A roots callback that answers with an error surfaces to the requesting handler as an MCPError.",
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2322); there is no error answer to a roots request under MRTR -- "
            "the client does not replay the call with an error message, as the server is not waiting. No "
            "replacement."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "roots:list:empty": Requirement(
        source=f"{SPEC_BASE_URL}/client/roots#listing-roots",
        behavior="An empty roots list is a valid response and reaches the handler as such.",
        removed_in="2026-07-28",
        superseded_by="roots:mrtr:list:empty",
        note="removed in 2026-07-28 (SEP-2322); roots/list now rides MRTR inputRequests.",
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
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
        removed_in="2026-07-28",
        superseded_by="roots:mrtr:capability:not-declared",
        note=(
            "removed in 2026-07-28 (SEP-2322); the client no longer answers roots requests (the -32601 "
            "answer plane is gone) -- the surviving protection is the server-side embed gate."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
    ),
    "roots:mrtr:list:basic": Requirement(
        source=f"{SPEC_2026_BASE_URL}/client/roots#listing-roots",
        behavior=(
            "An embedded roots/list request in an input_required result is fulfilled by the client's roots "
            "callback, and the returned roots (uri, name) reach the retried handler in inputResponses."
        ),
        added_in="2026-07-28",
        supersedes=("roots:list:basic",),
    ),
    "roots:mrtr:list:empty": Requirement(
        source=f"{SPEC_2026_BASE_URL}/client/roots#listing-roots",
        behavior=(
            "An empty roots list returned by the client roots callback for an embedded roots/list request "
            "reaches the retried handler as such."
        ),
        added_in="2026-07-28",
        supersedes=("roots:list:empty",),
    ),
    "roots:mrtr:capability:not-declared": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/mrtr#server-requirements-basic-workflow",
        behavior=(
            "The server does not place a roots/list request in an input_required result's inputRequests "
            "for a client that did not declare the roots capability."
        ),
        divergence=Divergence(
            note=(
                "The embed gate is not implemented: an input_required result carrying a roots/list "
                "request for a client that did not declare the roots capability is transmitted as-is, "
                "and the violation surfaces as the client driver's refusal (INVALID_REQUEST, 'List "
                "roots not supported') aborting the call."
            ),
            issue="L109",
        ),
        added_in="2026-07-28",
        supersedes=("roots:list:not-supported",),
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
        removed_in="2026-07-28",
        superseded_by="client:listen:auto-refresh",
        note=(
            "removed in 2026-07-28 (SEP-2575); unsolicited list_changed notifications retired -- the modern "
            "auto-refresh reacts to changes published on a subscriptions/listen stream."
        ),
    ),
    "client:listen:auto-refresh": Requirement(
        source="sdk",
        behavior=(
            "A client configured with listChanged auto-refresh, on a modern connection, opens a "
            "subscriptions/listen stream and on each published change re-fetches the corresponding list "
            "and delivers the fresh result to its callback."
        ),
        added_in="2026-07-28",
        supersedes=("client:list-changed:auto-refresh",),
        deferred=(
            "Not implemented in the SDK: the client has no subscriptions/listen API and no list-changed "
            "auto-refresh mechanism."
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
            "A tool registered or removed after the client connected appears in (or disappears from) "
            "tools/list results, and the change is announced with a list_changed notification."
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
    # Caching (SEP-2549, 2026-07-28)
    # ═══════════════════════════════════════════════════════════════════════════
    "caching:hints:prompts-list": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#cacheable-results",
        behavior=(
            "prompts/list results at 2026-07-28 carry the caching hints -- ttlMs >= 0 and "
            "cacheScope -- alongside resultType complete; handler-authored hint values reach the "
            "client unmodified."
        ),
        added_in="2026-07-28",
        note=(
            "Completes the spec's six-operation MUST together with "
            "hosting:http:modern:cacheable-stamping (tools/list, resources/list, resources/read) "
            "and caching:hints:server-discover (server/discover). The server-side "
            "'ttlMs >= 0' MUST is by construction: CacheableResult.ttl_ms is Field(ge=0), so a "
            "violating result is unconstructible through the typed API."
        ),
    ),
    "caching:hints:resources-templates-list": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#cacheable-results",
        behavior=(
            "resources/templates/list results at 2026-07-28 carry the caching hints -- "
            "ttlMs >= 0 and cacheScope -- alongside resultType complete; handler-authored hint "
            "values reach the client unmodified."
        ),
        added_in="2026-07-28",
        note=(
            "The sixth operation of the spec's cacheable-results MUST; see "
            "caching:hints:prompts-list for the family map."
        ),
    ),
    "caching:hints:server-discover": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#cacheable-results",
        behavior=(
            "server/discover results at 2026-07-28 carry the caching hints -- ttlMs >= 0 and "
            "cacheScope -- alongside resultType complete."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "Only observable over streamable HTTP: server/discover is served only by the modern "
            "HTTP entry (the in-memory 2026 connection synthesizes its DiscoverResult client-side "
            "and never sends the request). The pinned 0/private values are the SDK's "
            "CacheableResult defaults -- no handler authors discover hints -- so the test pins "
            "the stamping mechanism, not authored pass-through. Completes the six-operation map "
            "with caching:hints:prompts-list (family index) and hosting:http:modern:cacheable-stamping."
        ),
    ),
    "caching:pagination:same-scope-all-pages": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#interaction-with-pagination",
        behavior=(
            "Every page of one paginated list request carries the same cacheScope: the scope of "
            "the first page applies to all subsequent pages of that request."
        ),
        added_in="2026-07-28",
        divergence=Divergence(
            note=(
                "The SDK applies no cross-page cacheScope consistency: each page's scope is "
                "whatever that handler invocation returned, and a handler authoring mismatched "
                "scopes across one cursor walk is forwarded unmodified with no error. The "
                "stateless 2026 entry cannot correlate pages of 'a given list request' without "
                "encoding state in the (server-minted, opaque) cursor, so enforcement is a real "
                "SDK design question; today the spec MUST is delegated entirely to the handler "
                "author. The SDK's own defaults are trivially cross-page consistent."
            ),
            issue="L111",
        ),
    ),
    "caching:ttl:absent-defaults-zero": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#time-to-live-ttl-field",
        behavior=(
            "When a result arrives with no ttlMs (a pre-2026 server), the client surfaces the "
            "default 0 -- immediately stale -- rather than failing or inventing freshness."
        ),
        removed_in="2026-07-28",
        note=(
            "Era-bound for constructibility, matching the spec's own scoping ('this should only "
            "occur in older server versions'): the 2026-07-28 wire surface makes ttlMs/cacheScope "
            "required, so absence at 2026 is a validation error, not a defaulting case. The "
            "companion cacheScope private default the test also pins is the SDK's chosen safe "
            "default -- the spec sentence covers only ttlMs."
        ),
    ),
    "caching:ttl:zero-immediately-stale": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#time-to-live-ttl-field",
        behavior=(
            "A result stamped ttlMs 0 is immediately stale: the client re-fetches on every "
            "access instead of serving the previous response."
        ),
        added_in="2026-07-28",
        note=(
            "Satisfied by construction at this pin -- the client has no response cache, so every "
            "call re-fetches regardless of ttlMs (the positive-ttl fresh window is the deferred "
            "sibling caching:ttl:positive-fresh-window). The pin is the regression bar for a "
            "future cache: one that wrongly served a ttlMs 0 entry would fail it."
        ),
    ),
    "caching:input-required:no-hints": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#cacheable-results",
        behavior=(
            "An interim resultType input_required result carries no caching hints on the wire, "
            "while the terminal complete result of the very same exchange carries both ttlMs and "
            "cacheScope."
        ),
        added_in="2026-07-28",
        note=(
            "The no-hints half is by construction (InputRequiredResult does not extend "
            "CacheableResult and rejects extras); the wire pin proves the serialized frame, where "
            "typed models hide absent-vs-default. The sentence's 'are not cacheable' consumer "
            "half is unobservable: the client has no response cache (see the caching:key:* and "
            "caching:freshness:* deferrals)."
        ),
    ),
    "caching:ttl:negative-treated-as-zero": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#time-to-live-ttl-field",
        behavior="A negative ttlMs on an inbound result is ignored and treated as 0.",
        added_in="2026-07-28",
        divergence=Divergence(
            note=(
                "The client rejects a negative ttlMs with a pydantic ValidationError out of the "
                "request call instead of ignoring it and treating it as 0: Field(ge=0) on the "
                "2026-07-28 wire surface (and on the monolith CacheableResult) raises before any "
                "coerce-to-zero leniency could run, and there is no response cache for 'treat as "
                "0' to act on. The gap is asymmetric: ge=0 on server-authored EMISSION is correct "
                "by-construction strictness (a conformant server can never author a negative "
                "ttlMs through the typed API); the gap is ONLY the client's inbound parse, which "
                "validates before any clamp-to-0 could apply. The remedy is receive-side leniency "
                "-- clamp a negative inbound ttlMs to 0 before validation -- NOT loosening the "
                "shared type, which would silently bless negative emission server-side."
            ),
            issue="L112",
        ),
    ),
    "caching:ttl:positive-fresh-window": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#time-to-live-ttl-field",
        behavior=(
            "A positive ttlMs opens a fresh window: a caching client considers the result fresh "
            "for that many milliseconds after receipt and need not re-fetch on access within it."
        ),
        added_in="2026-07-28",
        deferred=(
            "Not implemented in the SDK: the client has no SEP-2549 response cache -- nothing in "
            "src/mcp/client/ consults ttl_ms after deserialization, and every list call "
            "unconditionally re-issues the request -- so a positive ttlMs never produces a fresh "
            "window in which a re-fetch is suppressed."
        ),
    ),
    "caching:freshness:stale-refetch-on-access": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#freshness-calculation",
        behavior=("Once a cached response's TTL expires it is stale, and the client re-fetches on the next access."),
        added_in="2026-07-28",
        deferred=(
            "Not implemented in the SDK: the client has no SEP-2549 response cache, so the "
            "fresh-serve half of the staleness transition does not exist -- every access is "
            "already a fetch -- and the transition is unconstructible."
        ),
    ),
    "caching:freshness:no-background-polling": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#freshness-calculation",
        behavior=(
            "The client does not treat TTL as a polling interval: expiry alone triggers no "
            "automatic background re-fetch; freshness is checked on access."
        ),
        added_in="2026-07-28",
        deferred=(
            "Not implemented in the SDK: the client has no SEP-2549 response cache and never "
            "reads a result's ttl_ms, so there is no TTL machinery whose non-polling could be "
            "observed -- the test would assert that absent code did not run."
        ),
    ),
    "caching:key:no-cross-key-serve": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#cache-key",
        behavior=(
            "A cached response is keyed by method plus result-affecting parameters; it is never "
            "served for a request whose method or parameters differ."
        ),
        added_in="2026-07-28",
        deferred=(
            "Not implemented in the SDK: the client never serves a cached response at all (no "
            "SEP-2549 response cache exists under src/mcp/client/), so cache-key discipline has "
            "no positive half to exercise and a two-requests-both-reach-the-server test would "
            "pass vacuously."
        ),
    ),
    "caching:key:mrtr-retry-not-cached": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#cache-key",
        behavior=(
            "Results produced by an MRTR retry -- a request carrying inputResponses or "
            "requestState -- are never cached: they depend on inputs outside the cache key."
        ),
        added_in="2026-07-28",
        deferred=(
            "Not implemented in the SDK: the client has no SEP-2549 response cache, so there is "
            "no cacher whose refusal to store an MRTR-retry result could be driven or observed; "
            "the negative is indistinguishable from 'the client never caches anything'."
        ),
    ),
    "caching:notification:invalidates-fresh-cache": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#interaction-with-notifications",
        behavior=(
            "A relevant notification received while a cached response is still fresh invalidates "
            "it: the entry becomes immediately stale regardless of remaining TTL."
        ),
        added_in="2026-07-28",
        deferred=(
            "Not implemented in the SDK: there is no SEP-2549 response cache with a freshness "
            "clock for a notification to invalidate, and the client has no server-to-client "
            "list_changed pipeline that could feed one (the only list_changed code in "
            "src/mcp/client/ is the outbound roots/list_changed sender)."
        ),
    ),
    "caching:pagination:per-page-independent": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#interaction-with-pagination",
        behavior=(
            "Each page of a paginated list is an independently cacheable response: each carries "
            "its own ttlMs, and each page's freshness clock starts at its own receipt time."
        ),
        added_in="2026-07-28",
        deferred=(
            "Not implemented in the SDK: the per-receipt freshness clock and independent expiry "
            "need a client response cache that records per-page receipt times; none exists. The "
            "carriage half (each page carries its own ttlMs, set per handler invocation) is "
            "expressible today and can be split out if wanted."
        ),
    ),
    "caching:pagination:expired-page-refetch-by-cursor": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#interaction-with-pagination",
        behavior=(
            "When one cached page expires, the client re-fetches that page by its cursor; fresh "
            "sibling pages are not re-fetched."
        ),
        added_in="2026-07-28",
        deferred=(
            "Not implemented in the SDK: the client has no SEP-2549 response cache, no per-page "
            "ttlMs bookkeeping, and no autonomous re-fetch loop -- the list methods are one-shot "
            "and caller-cursored -- so there is no expired cached page to selectively re-fetch."
        ),
    ),
    "caching:pagination:invalid-cursor-discards-all": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#interaction-with-pagination",
        behavior=(
            "When a previously valid cursor starts erroring, the client discards all cached "
            "pages and re-fetches the list from the beginning."
        ),
        added_in="2026-07-28",
        deferred=(
            "Not implemented in the SDK: the client retains no list pages (no SEP-2549 response "
            "cache), so there are no cached pages to discard and no re-fetch-from-the-beginning "
            "reaction to observe; the -32602 surfacing itself is pinned by pagination:invalid-cursor."
        ),
    ),
    "caching:scope:private-not-shared-across-auth-contexts": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#cache-scope-field",
        behavior=(
            "A private-scoped cache is never shared across authorization contexts: a different "
            "access token requires a different cache."
        ),
        added_in="2026-07-28",
        deferred=(
            "Not implemented in the SDK: the client has no SEP-2549 response cache and therefore "
            "no per-authorization-context cache keying -- there is no stored entry that could be "
            "served across an access-token change, on either side of the connection."
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
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    "tasks:bidirectional": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#definitions",
        behavior="Task APIs are bidirectional: the server may create, get, list, and cancel tasks on the client.",
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    "tasks:cancel:no-handler-abort": Requirement(
        source="sdk",
        behavior=(
            "tasks/cancel marks the task cancelled without aborting the originating request handler "
            "(the spec says receivers SHOULD attempt to stop execution)."
        ),
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    "tasks:cancel:remains-cancelled": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#task-cancellation",
        behavior=(
            "After tasks/cancel, the task remains cancelled even if the underlying handler subsequently "
            "completes or fails."
        ),
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    "tasks:cancel:terminal-rejected": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#task-cancellation",
        behavior="tasks/cancel on a task already in a terminal state returns Invalid params (-32602).",
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    "tasks:cancel:working": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#task-cancellation",
        behavior="tasks/cancel on a working task transitions it to cancelled and returns the updated task.",
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    "tasks:create:ttl-honored": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#ttl-and-resource-management",
        behavior=(
            "tasks/get responses include the actual ttl applied by the receiver (or null for unlimited); "
            "the create-task result carries the same value."
        ),
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    "tasks:create:via-tool-call": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#creating-tasks",
        behavior="A task-augmented tools/call returns a create-task result instead of the tool result.",
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    "tasks:get": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#getting-tasks",
        behavior="tasks/get returns the task's current status, ttl, timestamps, and status message.",
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    "tasks:lifecycle:initial-working": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#task-status-lifecycle",
        behavior="A newly created task has status 'working'.",
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    "tasks:lifecycle:input-required": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#input-required-status",
        behavior=(
            "While a task awaits a side-channel client response its status is input_required; once the "
            "response arrives the task leaves input_required (typically returning to working)."
        ),
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    "tasks:list:invalid-cursor": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#protocol-errors",
        behavior="tasks/list with an invalid cursor returns Invalid params (-32602).",
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension (tasks/list dropped in the redesign)."
        ),
    ),
    "tasks:list:pagination": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#listing-tasks",
        behavior="tasks/list returns created tasks and supports cursor pagination.",
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension (tasks/list dropped in the redesign)."
        ),
    ),
    "tasks:no-capability:ignore-task-param": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#task-support-and-handling",
        behavior=(
            "A receiver that did not declare task capability for a request type processes the request "
            "normally and returns the ordinary result, ignoring the task augmentation."
        ),
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    "tasks:progress:after-create": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#task-progress-notifications",
        behavior=(
            "After the create-task result, progress notifications keyed to the original progress token "
            "continue to reach the caller until the task is terminal."
        ),
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    "tasks:request-cancel:no-task-cancel": Requirement(
        source="sdk",
        behavior="A cancellation notification for the originating request does not auto-cancel the created task.",
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    "tasks:result:failed": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#task-execution-errors",
        behavior="tasks/result for a failed task returns the failure result (isError true).",
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension (tasks/result dropped in the redesign)."
        ),
    ),
    "tasks:result:related-task-meta": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#related-task-metadata",
        behavior="The tasks/result response carries related-task _meta naming the requested task.",
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension (tasks/result dropped in the redesign)."
        ),
    ),
    "tasks:result:terminal": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#result-retrieval",
        behavior="tasks/result for a completed task returns the stored result of the original request type.",
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension (tasks/result dropped in the redesign)."
        ),
    ),
    "tasks:side-channel:drain-fifo": Requirement(
        source="sdk",
        behavior="tasks/result drains queued related-task messages in FIFO order before returning the final result.",
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension (tasks/result side-channel dropped in the redesign)."
        ),
    ),
    "tasks:side-channel:drop-on-cancel": Requirement(
        source="sdk",
        behavior="When a task is cancelled before tasks/result, queued related-task messages are dropped.",
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension (tasks/result side-channel dropped in the redesign)."
        ),
    ),
    "tasks:side-channel:elicitation": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#input-required-status",
        behavior=(
            "An elicitation issued mid-task is delivered through the tasks/result side-channel, and the "
            "client's response routes back to the handler."
        ),
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension (tasks/result side-channel dropped in the redesign)."
        ),
    ),
    "tasks:side-channel:queue": Requirement(
        source="sdk",
        behavior=(
            "Server-to-client requests with related-task metadata sent while no tasks/result is open are queued."
        ),
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension (tasks/result side-channel dropped in the redesign)."
        ),
    ),
    "tasks:side-channel:sampling": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#input-required-status",
        behavior=(
            "A sampling request issued mid-task is delivered through the tasks/result side-channel, and "
            "the client's response routes back to the task."
        ),
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension (tasks/result side-channel dropped in the redesign)."
        ),
    ),
    "tasks:side-channel:stream": Requirement(
        source="sdk",
        behavior=(
            "Calling tasks/result while the task is working streams related-task messages as they are "
            "produced, then returns the result."
        ),
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension (tasks/result side-channel dropped in the redesign)."
        ),
    ),
    "tasks:status-notification": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#task-status-notification",
        behavior="Task status notifications deliver status updates carrying the full task fields.",
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    "tasks:tool-level:forbidden-with-task-32601": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#tool-level-negotiation",
        behavior=(
            "A task-augmented tools/call on a tool that does not support tasks returns Method not found (-32601)."
        ),
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    "tasks:tool-level:required-no-task-32601": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#tool-level-negotiation",
        behavior=("A plain tools/call on a tool that requires task augmentation returns Method not found (-32601)."),
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    "tasks:unknown-id": Requirement(
        source=f"{SPEC_BASE_URL}/basic/utilities/tasks#protocol-errors",
        behavior="tasks/get, tasks/result, and tasks/cancel for an unknown task id return Invalid params (-32602).",
        deferred=_TASKS_DEFERRAL,
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2663); tasks moved out of core into the io.modelcontextprotocol/tasks "
            "extension."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Extensions (SEP-2133): client-side result claims and the capability ad
    # ═══════════════════════════════════════════════════════════════════════════
    "extensions:client:claimed-result-resolved": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic#resulttype",
        behavior=(
            "A tools/call answered with an extension-claimed resultType is finished by the owning "
            "ClientExtension's claim resolver, and Client.call_tool returns the resolver's ordinary "
            "CallToolResult. The resolver may send follow-up requests through the session it is handed."
        ),
        added_in="2026-07-28",
    ),
    "extensions:client:claimed-result-undeclared-invalid": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic#resulttype",
        behavior=(
            "A resultType unrecognized by the client is invalid: a claimed shape delivered to a client that "
            "did not construct the owning extension fails result validation (the supported set is core plus "
            "declared claims, never more)."
        ),
        added_in="2026-07-28",
        note=(
            "Known leniency: the monolith result surface still accepts an unknown tag when the payload "
            "also parses as a complete core result (open result_type, extras ignored). Rejecting tags "
            "outside core plus active claims is a tracked follow-up ruling."
        ),
    ),
    "extensions:client:capability-ad:gates-server-behaviour": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic#resulttype",
        behavior=(
            "The per-request _meta capability ad carries each declared extension's identifier and settings, "
            "and is what entitles the server to substitute that extension's claimed shapes: a server "
            "extension gating on the ad sees the declared settings, and refuses a non-declaring client with "
            "-32021 (missing required client capability)."
        ),
        added_in="2026-07-28",
    ),
    "extensions:client:capability-ad:legacy-omits-claimed": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic#resulttype",
        behavior=(
            "On a legacy connection no claim can activate, and the initialize capability ad omits "
            "claim-bearing identifiers in the same breath (claim-less identifiers still advertise), so the "
            "client never advertises an extension whose claimed shapes it would reject."
        ),
        removed_in="2026-07-28",
        note=(
            "The legacy-era half of the ad/claims coupling: only a handshake connection can exhibit it, so "
            "the version window ends where the modern era begins."
        ),
        arm_exclusions=(ArmExclusion(reason="requires-session", transport="streamable-http-stateless"),),
    ),
    "extensions:client:notification-binding-delivery": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic#resulttype",
        behavior=(
            "A vendor server notification bound by a ClientExtension's NotificationBinding is validated "
            "against the binding's params type and delivered to its handler serially, in dispatch order."
        ),
        added_in="2026-07-28",
        deferred=(
            "Covered at session tier by tests/client/test_session_notification_bindings.py: no public "
            "server-side surface emits vendor-method notifications (ServerNotification is a closed union), "
            "and HTTP-modern arrival additionally needs the subscriptions/listen client runtime."
        ),
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
        note="Only observable over streamable HTTP: exercises the stateful HTTP framing end to end.",
    ),
    "transport:streamable-http:json-response": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#streamable-http",
        behavior="The interaction round trip works when the server answers with plain JSON instead of SSE.",
        transports=("streamable-http",),
        note="Only observable over streamable HTTP: JSON-response mode is an HTTP framing option.",
    ),
    "transport:streamable-http:stateless": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#streamable-http",
        behavior=(
            "The interaction round trip works in stateless mode, where every request is served by a "
            "fresh transport with no session id."
        ),
        transports=("streamable-http",),
        note="Only observable over streamable HTTP: stateless mode is an HTTP hosting option.",
    ),
    "transport:streamable-http:notifications": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#streamable-http",
        behavior=(
            "Notifications emitted during a request reach the client's callbacks over the streamable HTTP framing."
        ),
        transports=("streamable-http",),
        note="Only observable over streamable HTTP: per-request SSE streams are HTTP-specific.",
    ),
    "transport:streamable-http:stateless-restrictions": Requirement(
        source="sdk",
        behavior=(
            "A handler that attempts a server-initiated request in stateless mode fails with an error "
            "result, because there is no session to call back through."
        ),
        transports=("streamable-http",),
        note="Only observable over streamable HTTP: stateless mode is an HTTP hosting option.",
    ),
    "transport:streamable-http:unrelated-messages": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#streamable-http",
        behavior=(
            "A server-to-client message that is not related to an in-flight request is routed to the "
            "standalone GET stream and delivered to the client listening on it, not to any request's "
            "own stream."
        ),
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); the standalone GET stream is replaced by subscriptions/listen.",
    ),
    "transport:streamable-http:server-to-client": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#streamable-http",
        behavior=(
            "A server-initiated request nested inside an in-flight call round-trips over stateful streamable HTTP."
        ),
        transports=("streamable-http",),
        removed_in="2026-07-28",
        superseded_by="elicitation:mrtr:form:basic",
        note=(
            "removed in 2026-07-28 (SEP-2322); server-initiated requests are forbidden on streamable HTTP, "
            "replaced by MRTR input requests embedded in InputRequiredResult."
        ),
    ),
    "transport:streamable-http:resumability": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#streamable-http",
        behavior="A client that reconnects with Last-Event-ID receives the events it missed.",
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); Last-Event-ID resumability/redelivery dropped, no replacement.",
    ),
    "transport:sse": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#backwards-compatibility",
        behavior=(
            "A client connected over the legacy HTTP+SSE transport completes the handshake and round-trips "
            "requests, with server messages delivered on the SSE stream."
        ),
        transports=("sse",),
        note="Only observable over the legacy SSE transport.",
    ),
    "transport:sse:endpoint-event": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#backwards-compatibility",
        behavior="Opening the SSE stream delivers an `endpoint` event naming the message-POST URL as the first event.",
        transports=("sse",),
        note="Only observable over the legacy SSE transport.",
    ),
    "transport:sse:post:session-routing": Requirement(
        source="sdk",
        behavior=(
            "The endpoint URL carries a fresh session identifier; the server registers the session before "
            "the endpoint event is sent and releases it when the stream disconnects, and a POST that names "
            "no session id, a malformed session id, or an unknown session id is rejected (400/400/404)."
        ),
        transports=("sse",),
        note="Only observable over the legacy SSE transport.",
    ),
    "transport:stdio": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#stdio",
        behavior=(
            "A Client connected to a real SDK Server over stdio initializes, calls a tool with arguments, "
            "and receives notifications and results over the child process's stdin/stdout."
        ),
        transports=("stdio",),
        note="Only observable over stdio: exercises the child-process framing end to end.",
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Hosting: session lifecycle
    # ═══════════════════════════════════════════════════════════════════════════
    "hosting:session:cors-expose": Requirement(
        source="sdk",
        behavior="CORS configuration exposes the Mcp-Session-Id header so browser clients can read it.",
        transports=("streamable-http",),
        deferred="Not implemented in the SDK: CORS configuration is left to the hosting ASGI application.",
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2567); Mcp-Session-Id removed, no replacement.",
    ),
    "hosting:session:create": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior=(
            "An initialize POST without a session id creates a session and returns Mcp-Session-Id in the "
            "response headers."
        ),
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2567); Mcp-Session-Id and protocol-level sessions removed, no replacement "
            "(cross-call state moves to explicit server-minted handles)."
        ),
    ),
    "hosting:session:delete": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior="DELETE with a valid Mcp-Session-Id terminates the session.",
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2567); session DELETE removed with Mcp-Session-Id, no replacement.",
    ),
    "hosting:session:id-charset": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior="Generated Mcp-Session-Id values contain only visible ASCII characters.",
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2567); Mcp-Session-Id removed, no replacement.",
    ),
    "hosting:session:isolation": Requirement(
        source="sdk",
        behavior="Each session gets its own server instance; closing one session does not affect others.",
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2567); per-session server instances retired with Mcp-Session-Id, no "
            "replacement."
        ),
    ),
    "hosting:session:missing-id": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior="A non-initialize POST without Mcp-Session-Id in stateful mode returns 400.",
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2567); Mcp-Session-Id validation removed, no replacement.",
    ),
    "hosting:session:post-termination-404": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior=(
            "After a session is terminated, any further request carrying that session ID is answered with "
            "404 Not Found."
        ),
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2567); Mcp-Session-Id removed, no replacement.",
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
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2567); per-session initialize guard retired with Mcp-Session-Id, no "
            "replacement."
        ),
    ),
    "hosting:session:reuse": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior="A POST carrying a valid Mcp-Session-Id routes to that session's transport with state preserved.",
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2567); Mcp-Session-Id routing removed, no replacement.",
    ),
    "hosting:session:unknown-id": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior="A POST, GET, or DELETE with an unknown Mcp-Session-Id returns 404.",
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2567); Mcp-Session-Id removed, no replacement.",
    ),
    "hosting:stateless:concurrent-clients": Requirement(
        source="sdk",
        behavior="Multiple independent clients can connect to a stateless server concurrently.",
        transports=("streamable-http",),
        note="Stateless mode is a streamable-HTTP hosting option.",
    ),
    "hosting:stateless:no-reuse": Requirement(
        source="sdk",
        behavior="A stateless per-request transport cannot be reused for a second request.",
        transports=("streamable-http",),
        note="Stateless mode is a streamable-HTTP hosting option.",
    ),
    "hosting:stateless:no-session-id": Requirement(
        source="sdk",
        behavior="In stateless mode no Mcp-Session-Id is emitted and no session validation is performed.",
        transports=("streamable-http",),
        note="Stateless mode is a streamable-HTTP hosting option; Mcp-Session-Id is an HTTP header.",
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
        note="Auth is enforced at the HTTP layer; the AS router is an ASGI app.",
    ),
    "hosting:auth:aud-validation": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#access-token-usage",
        behavior="The resource server validates that the token audience matches its resource identifier.",
        transports=("streamable-http",),
        note="Auth is enforced at the HTTP layer.",
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
        note="Auth is enforced at the HTTP layer.",
    ),
    "hosting:auth:expired-401": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#token-handling",
        behavior="An expired token returns 401 invalid_token.",
        transports=("streamable-http",),
        note="Auth is enforced at the HTTP layer; 401 is an HTTP status code.",
        divergence=Divergence(
            note="The challenge carries no `scope` parameter; see the note on hosting:auth:missing-401.",
        ),
    ),
    "hosting:auth:invalid-401": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#token-handling",
        behavior="A malformed bearer token or token-verification failure returns 401 with WWW-Authenticate.",
        transports=("streamable-http",),
        note="Auth is enforced at the HTTP layer; 401 is an HTTP status code.",
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
        note="Auth is enforced at the HTTP layer; well-known endpoints are HTTP routes.",
    ),
    "hosting:auth:missing-401": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#protected-resource-metadata-discovery-requirements",
        behavior=(
            "A request without an Authorization header is rejected with 401; the WWW-Authenticate header "
            "carries resource_metadata (one of the spec's two permitted discovery mechanisms)."
        ),
        transports=("streamable-http",),
        note="Auth is enforced at the HTTP layer; 401 is an HTTP status code.",
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
        note="Auth is enforced at the HTTP layer; PRM is served over HTTP.",
    ),
    "hosting:auth:query-token-ignored": Requirement(
        source="sdk",
        behavior=(
            "An access token presented in the URI query string is not accepted; the request is treated as "
            "unauthenticated."
        ),
        transports=("streamable-http",),
        note="Auth is enforced at the HTTP layer; query strings are URL-specific.",
    ),
    "hosting:auth:scope-403": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#runtime-insufficient-scope-errors",
        behavior=(
            "A token lacking a required scope returns 403 with WWW-Authenticate carrying "
            "insufficient_scope, the required scope, and resource_metadata."
        ),
        transports=("streamable-http",),
        note="Auth is enforced at the HTTP layer; 403 is an HTTP status code.",
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
        note="Auth is enforced at the HTTP layer; the bundled AS is an ASGI app.",
    ),
    "hosting:auth:as:verifier-mismatch": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#authorization-code-protection",
        behavior=(
            "The bundled token endpoint rejects an authorization-code exchange whose `code_verifier` "
            "does not hash to the stored `code_challenge` with `invalid_grant`."
        ),
        transports=("streamable-http",),
        note="Auth is enforced at the HTTP layer; the bundled AS is an ASGI app.",
    ),
    "hosting:auth:as:code-single-use": Requirement(
        source="sdk",
        behavior=(
            "An authorization code can be exchanged exactly once; a second exchange of the same code "
            "is rejected with `invalid_grant`. Enforced by the provider deleting the code on first use; "
            "the handler relies on `load_authorization_code` returning None."
        ),
        transports=("streamable-http",),
        note="Auth is enforced at the HTTP layer; the bundled AS is an ASGI app.",
    ),
    "hosting:auth:as:redirect-uri-binding": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#open-redirection",
        behavior=(
            "The bundled token endpoint rejects an authorization-code exchange whose `redirect_uri` "
            "differs from the one used at authorize; the bundled authorize endpoint rejects a "
            "`redirect_uri` not in the client's registered list without redirecting to it."
        ),
        transports=("streamable-http",),
        note="Auth is enforced at the HTTP layer; the bundled AS is an ASGI app.",
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
        note="Auth is enforced at the HTTP layer; the bundled AS is an ASGI app.",
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
        note="Auth is enforced at the HTTP layer; Cache-Control is an HTTP header.",
    ),
    "hosting:auth:as:register-error-response": Requirement(
        source="sdk",
        behavior=(
            "The bundled registration endpoint answers invalid client metadata with HTTP 400 and an "
            "RFC 7591 error body."
        ),
        transports=("streamable-http",),
        note="Auth is enforced at the HTTP layer; the bundled AS is an ASGI app.",
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
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); Last-Event-ID resumability dropped, no replacement.",
    ),
    "hosting:resume:buffered-replay": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#resumability-and-redelivery",
        behavior="Notifications emitted while no client is connected are replayed in order on reconnect.",
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); SSE stream resumability/redelivery dropped, no replacement.",
    ),
    "hosting:resume:close-stream": Requirement(
        source="sdk",
        behavior="Handlers can close an SSE stream cleanly when an event store is configured.",
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); the event-store / resumability path is dropped, no replacement.",
    ),
    "hosting:resume:event-ids": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#resumability-and-redelivery",
        behavior="With an event store configured, every SSE event carries an id field.",
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); SSE event-id assignment for resumability dropped, no replacement.",
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
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2575); the priming-event / retry-hint requirement is dropped with "
            "resumability, no replacement."
        ),
    ),
    "hosting:resume:replay": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#resumability-and-redelivery",
        behavior="GET with Last-Event-ID replays stored events for that stream after the given id.",
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); Last-Event-ID replay dropped, no replacement.",
    ),
    "hosting:resume:stream-scoped": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#resumability-and-redelivery",
        behavior="Replay via Last-Event-ID returns only messages from the stream that event id belongs to.",
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); Last-Event-ID replay dropped, no replacement.",
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Hosting: HTTP semantics
    # ═══════════════════════════════════════════════════════════════════════════
    "hosting:http:accept-406": Requirement(
        source="sdk",
        behavior="A request whose Accept header does not allow the response representation returns 406.",
        transports=("streamable-http",),
        note="Only observable over HTTP: 406 is an HTTP status code.",
    ),
    "hosting:http:batch": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior=(
            "A POST body is a single JSON-RPC message; batched arrays are rejected for protocol revisions "
            "that forbid them."
        ),
        transports=("streamable-http",),
        note="Only observable over HTTP: POST-body framing is HTTP-specific.",
    ),
    "hosting:http:content-type-415": Requirement(
        source="sdk",
        behavior="A POST with a Content-Type other than application/json returns 415.",
        transports=("streamable-http",),
        note="Only observable over HTTP: 415 is an HTTP status code.",
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
        removed_in="2026-07-28",
        superseded_by="hosting:http:modern:disconnect-cancels-handler",
        note=(
            "removed in 2026-07-28 (SEP-2575); resumability dropped and the rule is inverted (closing the response "
            "stream is now the HTTP cancellation signal), no replacement."
        ),
    ),
    "hosting:http:dns-rebinding": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#security-warning",
        behavior=(
            "The Origin header is validated on every incoming connection; a request with an invalid "
            "Origin is rejected with 403 Forbidden."
        ),
        transports=("streamable-http",),
        note="Only observable over HTTP: Origin is an HTTP header.",
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
        note="Only observable over HTTP: response Content-Type is HTTP-specific.",
    ),
    "hosting:http:method-405": Requirement(
        source="sdk",
        behavior="An unsupported HTTP method on the MCP endpoint returns 405.",
        transports=("streamable-http",),
        note="Only observable over HTTP: 405 is an HTTP status code.",
    ),
    "hosting:http:no-broadcast": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#multiple-connections",
        behavior=(
            "When multiple SSE streams are open for a session, each server-originated message is sent on "
            "exactly one stream, never duplicated."
        ),
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2567); the per-session multiple-connections section is removed with "
            "Mcp-Session-Id, no replacement."
        ),
    ),
    "hosting:http:notifications-202": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior="A POST containing only notifications or responses returns 202 with no body.",
        transports=("streamable-http",),
        note="Only observable over HTTP: 202 is an HTTP status code.",
    ),
    "hosting:http:onerror": Requirement(
        source="sdk",
        behavior="Transport-level rejections are reported through an error callback on the server transport.",
        transports=("streamable-http",),
        note="Only observable over HTTP: these rejections happen at the HTTP framing layer.",
        deferred="Not implemented in the SDK: the server transport has no error callback; rejections are logged.",
    ),
    "hosting:http:parse-error-400": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior=(
            "A POST body that is not valid JSON or not a valid JSON-RPC message is rejected with HTTP 400; "
            "the body may carry a JSON-RPC error response (the SDK sends a Parse error body)."
        ),
        transports=("streamable-http",),
        note="Only observable over HTTP: 400 is an HTTP status code.",
    ),
    "hosting:http:protocol-version-400": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#protocol-version-header",
        behavior="An invalid or unsupported MCP-Protocol-Version header returns 400 Bad Request.",
        transports=("streamable-http",),
        note="Only observable over HTTP: MCP-Protocol-Version is an HTTP header.",
    ),
    "hosting:http:protocol-version-default": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#protocol-version-header",
        behavior=(
            "When no MCP-Protocol-Version header is received and the version cannot be determined another "
            "way, the server assumes protocol version 2025-03-26."
        ),
        transports=("streamable-http",),
        note="Only observable over HTTP: MCP-Protocol-Version is an HTTP header.",
    ),
    "hosting:http:response-same-connection": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior=(
            "A response is delivered on the SSE stream opened by the POST that carried its request (or "
            "that stream's resumed continuation), not on an unrelated stream."
        ),
        transports=("streamable-http",),
        note="Only observable over HTTP: SSE stream affinity is HTTP-specific.",
    ),
    "hosting:http:second-sse-rejected": Requirement(
        source="sdk",
        behavior="A second concurrent standalone GET SSE stream on the same session is rejected.",
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); the standalone GET stream is replaced by subscriptions/listen.",
    ),
    "hosting:http:sse-close-after-response": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior="The server terminates a POST-initiated SSE stream after writing the JSON-RPC response.",
        transports=("streamable-http",),
        note="Only observable over HTTP: SSE stream lifecycle is HTTP-specific.",
    ),
    "hosting:http:standalone-sse": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#listening-for-messages-from-the-server",
        behavior="GET opens a standalone SSE stream that receives server-initiated messages.",
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); the standalone GET endpoint is replaced by subscriptions/listen.",
    ),
    "hosting:http:standalone-sse-no-response": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#listening-for-messages-from-the-server",
        behavior=(
            "The standalone GET SSE stream carries server requests and notifications but never a JSON-RPC "
            "response, except when resuming a prior request stream."
        ),
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); the standalone GET endpoint is replaced by subscriptions/listen.",
    ),
    "hosting:http:protocol-version-rejection-literal": Requirement(
        source="sdk",
        behavior=(
            "The streamable-HTTP version-rejection body contains the literal substring 'Unsupported "
            "protocol version', which other-SDK clients substring-match during negotiation; the modern "
            "request classifier is its only emission site."
        ),
        transports=("streamable-http",),
        note=(
            "Only observable over streamable HTTP: cross-SDK clients sniff this exact substring in the rejection body."
        ),
    ),
    "hosting:http:legacy-no-modern-vocabulary": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/versioning",
        behavior=(
            "A 2025-era streamable-HTTP exchange carries none of the 2026-07-28 wire vocabulary "
            "(resultType, ttlMs, cacheScope, io.modelcontextprotocol/* _meta keys, the 2026-07-28 "
            "version string, or Mcp-Method/Mcp-Name/Mcp-Param-* headers)."
        ),
        transports=("streamable-http",),
        note=(
            "Only observable over streamable HTTP: the assertion records HTTP headers and SSE frames "
            "at the transport seam."
        ),
    ),
    "hosting:http:modern:tools-call-stateless": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http",
        behavior=(
            "A 2026-07-28 tools/call POST is served without an initialize handshake and returns a "
            "result body carrying resultType: complete."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "Only observable over streamable HTTP: the modern entry handles a 2026-07-28 POST without "
            "an initialize handshake."
        ),
    ),
    "hosting:http:modern:no-session-id": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http",
        behavior="A 2026-07-28 response never carries an Mcp-Session-Id header.",
        added_in="2026-07-28",
        transports=("streamable-http",),
        note="Only observable over streamable HTTP: Mcp-Session-Id is a streamable-HTTP response header.",
    ),
    "hosting:http:modern:initialize-removed": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/index",
        behavior="A 2026-07-28 initialize request is answered with METHOD_NOT_FOUND at HTTP 404.",
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=("Only observable over streamable HTTP: the modern entry's method registry omits initialize."),
    ),
    "hosting:http:modern:legacy-fallthrough": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/versioning",
        behavior=(
            "Initialize-handshake-era traffic on the same /mcp endpoint reaches the legacy transport "
            "byte-unchanged: a 2025-era initialize handshake still completes. Any other "
            "MCP-Protocol-Version header routes to the modern entry, whose validation ladder rejects "
            "the envelope-less request with 400 INVALID_PARAMS."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "Only observable over streamable HTTP: routing branches on the MCP-Protocol-Version "
            "header at the same /mcp endpoint."
        ),
    ),
    "hosting:http:modern:handler-exception-internal-error": Requirement(
        source="sdk",
        behavior=(
            "An unhandled handler exception on the 2026-07-28 entry is returned as JSON-RPC error "
            "-32603 with a generic message that does not echo str(exc)."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note="Only observable over streamable HTTP: the modern entry's exception-to-JSONRPCError boundary.",
    ),
    "hosting:http:modern:discover-response-shape": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/index",
        behavior=(
            "A 2026-07-28 server/discover response carries supportedVersions, capabilities, and "
            "serverInfo, with supportedVersions naming the modern protocol revisions the server accepts."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note="Only observable over streamable HTTP: the raw result body is asserted at the wire.",
    ),
    "hosting:http:modern:removed-method-status-404": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/index",
        behavior=(
            "A method that exists at earlier protocol revisions but is removed at 2026-07-28 is "
            "answered METHOD_NOT_FOUND, and the modern entry maps that error code to HTTP 404."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "Only observable over streamable HTTP: the HTTP status is the assertion. Kernel-origin "
            "METHOD_NOT_FOUND travels through the same status table as classifier-origin errors."
        ),
    ),
    "hosting:http:modern:envelope-missing-key-status-400": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http",
        behavior=(
            "A 2026-07-28 request whose params._meta envelope omits a required reserved key is "
            "rejected as INVALID_PARAMS at HTTP 400 before kernel dispatch."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note="Only observable over streamable HTTP: the HTTP status is the assertion.",
    ),
    "hosting:http:modern:handler-error-status-via-table": Requirement(
        source="sdk",
        behavior=(
            "A handler-raised MCPError on the 2026-07-28 entry reaches the wire as a top-level "
            "JSON-RPC error with its data preserved, and the HTTP status is the error-code table "
            "entry for that code (handler-origin and classifier-origin errors share one table)."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note="Only observable over streamable HTTP: the modern entry's JSONRPCError-to-HTTP-status mapping.",
    ),
    "hosting:http:modern:disconnect-cancels-handler": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/patterns/cancellation#transport-specific-cancellation",
        behavior=(
            "On a 2026-07-28 streamable HTTP request, the client closing the SSE response stream is "
            "treated by the server as cancellation: the running handler is stopped and no JSON-RPC "
            "response is written."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        supersedes=("hosting:http:disconnect-not-cancel",),
        note="Only observable over streamable HTTP: stream closure is the transport-level cancellation signal.",
    ),
    "hosting:http:modern:cacheable-stamping": Requirement(
        source=f"{SPEC_2026_BASE_URL}/server/utilities/caching#cacheable-results",
        behavior=(
            "A 2026-07-28 cacheable result (tools/list, resources/list, resources/read, ...) reaches "
            "the wire as resultType complete plus the required ttlMs and cacheScope hints: "
            "handler-authored values pass through unchanged, and a result whose handler set neither "
            "is stamped with the defaults ttlMs 0 / cacheScope private."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "Only observable over streamable HTTP: typed client models default-fill ttl_ms/cache_scope, "
            "so absent-vs-stamped is a wire fact. The spec mandates the hints' presence and ttlMs >= 0; "
            "the 0/private default fill is the SDK's choice (CacheableResult defaults). Python has no "
            "operation-level cache-hint configuration (the TS createMcpHandler cacheHints precedence "
            "ladder); hints are authored per-result by the handler."
        ),
    ),
    "hosting:http:modern:json-response-mode": Requirement(
        source="sdk",
        behavior=(
            "With JSON response mode enabled, a 2026-07-28 request is answered with a single "
            "application/json body carrying only the terminal JSON-RPC response; request-scoped "
            "notifications emitted mid-call are dropped, not buffered."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "Only observable over streamable HTTP: response Content-Type and body framing are "
            "HTTP-specific. 2025-era sibling: hosting:http:json-response-mode. TS twin "
            "(typescript:hosting:entry:modern-response-mode) also has a forced-SSE response mode "
            "python does not implement: there is no responseMode equivalent, the SDK knob is the "
            "boolean json_response."
        ),
    ),
    "hosting:http:modern:lazy-sse-upgrade": Requirement(
        source="sdk",
        behavior=(
            "On the default response mode, a 2026-07-28 exchange is answered as a single "
            "application/json body when the handler emits nothing before its result, and upgrades to "
            "text/event-stream when the handler emits request-scoped notifications mid-call: the "
            "frames carry the notifications in emission order with the terminal response as the last "
            "frame."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "Only observable over streamable HTTP: the Content-Type commit is the assertion. The "
            "deferral window before a silent handler commits SSE anyway (_SSE_PING_INTERVAL) is not "
            "pinned: asserting it would need a real-time wait the suite refuses."
        ),
    ),
    "hosting:http:modern:response-stream-request-scoped": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#receiving-messages",
        behavior=(
            "Notifications on a 2026-07-28 SSE response stream relate to the originating client "
            "request: a notification emitted while serving request A travels only on A's response "
            "stream and never appears on another in-flight request's response."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "Only observable over streamable HTTP: which stream a message travels on is the assertion. "
            "Request-scoping is by construction on the modern entry (per-request sink); the test pins "
            "the observable consequence."
        ),
    ),
    "hosting:http:sse-x-accel-buffering": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#receiving-messages",
        behavior=(
            "When a 2026-07-28 response commits to an SSE stream, the response carries "
            "X-Accel-Buffering: no so reverse proxies deliver events unbuffered."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "Only observable over streamable HTTP: a response header is the assertion. Scoped to the "
            "modern entry (the SHOULD is new on the draft transport page); the legacy 2025-era "
            "SSE/streamable-http transports carry no such header and are not bound by this entry. The "
            "other 2026 SSE-initiation point, subscriptions/listen, is not constructible at this pin."
        ),
    ),
    "hosting:http:modern:header-name-case-insensitive": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#case-sensitivity",
        behavior=(
            "Standard request header names are matched case-insensitively: a 2026-07-28 POST whose "
            "MCP-Protocol-Version / Mcp-Method / Mcp-Name headers arrive under any casing is served, "
            "not rejected as missing a required header."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "Only observable over streamable HTTP. The in-process ASGI bridge lowercases header names "
            "into the scope (as every conformant ASGI server must), so the discriminating claim pinned "
            "end-to-end is that the server's lookups key on the lowercase canonical names "
            "(shared/inbound.py constants) rather than any cased spelling."
        ),
    ),
    "hosting:http:modern:missing-standard-header-rejected": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#server-validation",
        behavior=(
            "A 2026-07-28 request missing a required standard header -- Mcp-Method, or Mcp-Name on a "
            "name-bearing method -- is rejected with HTTP 400 and JSON-RPC error -32020 HeaderMismatch."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "Only observable over streamable HTTP: the HTTP status is half the assertion. Narrowed to "
            "the Mcp-Method / Mcp-Name arms: the MCP-Protocol-Version-missing arm belongs to the "
            "deferred hosting:http:modern:missing-protocol-version-header-rejected (a header-less "
            "request routes to the legacy transport; the rejecting modern-only posture is not "
            "implemented). The SDK reaches the rejection through its mismatch rung (absent header != "
            "body value), so the error message says 'does not match' rather than 'missing'."
        ),
    ),
    "hosting:http:modern:missing-protocol-version-header-rejected": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#protocol-version-header",
        behavior=(
            "A server that does not support clients predating the MCP-Protocol-Version header "
            "(pre-2025-06-18) rejects a request that omits the header with HTTP 400 and JSON-RPC "
            "error -32020 HeaderMismatch."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        deferred=(
            "Not implemented in the SDK: there is no modern-only server posture -- "
            "StreamableHTTPSessionManager.handle_request (src/mcp/server/streamable_http_manager.py) "
            "unconditionally routes a request without an MCP-Protocol-Version header to the legacy "
            "2025 transport (seeded with DEFAULT_NEGOTIATED_VERSION) instead of rejecting it, and the "
            "manager exposes no option to declare pre-2025-06-18 clients unsupported, so the "
            "rejecting arm is unconstructible."
        ),
        note=(
            "Only observable over streamable HTTP: MCP-Protocol-Version is an HTTP header. The "
            "implemented MAY arm (a header-less request is served as 2025-era traffic) is pinned by "
            "hosting:http:protocol-version-default and hosting:http:modern:legacy-fallthrough."
        ),
    ),
    "hosting:http:modern:protocol-version-meta-mismatch-400": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#protocol-version-header",
        behavior=(
            "A request whose MCP-Protocol-Version header and _meta protocolVersion envelope value are "
            "both individually valid but disagree is rejected with HTTP 400 and JSON-RPC error -32020 "
            "HeaderMismatch, before any supported-version check."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "Only observable over streamable HTTP: the SDK client derives header and envelope from one "
            "value (_make_modern_stamp) and can never produce the mismatch, so only a raw POST drives it."
        ),
    ),
    "hosting:http:modern:std-header-mismatch-400": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#server-validation",
        behavior=(
            "A 2026-07-28 request whose Mcp-Method or Mcp-Name header disagrees with the "
            "corresponding request-body value is rejected with HTTP 400 and a HeaderMismatch "
            "(-32020) JSON-RPC error."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "TS id: sep-2243:std-header:mismatch-rejected. Scope boundary: present-but-"
            "disagreeing Mcp-Method/Mcp-Name only -- the MCP-Protocol-Version mismatch is "
            "hosting:http:modern:protocol-version-meta-mismatch-400 and the missing-header "
            "conditions are hosting:http:modern:missing-standard-header-rejected."
        ),
    ),
    "hosting:http:modern:sentinel-decoded-before-validation": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#value-encoding",
        behavior=(
            "A base64-sentinel-encoded Mcp-Name header value is decoded before server validation "
            "compares it to the request body value, so an encoded-but-decode-matching value is served "
            "rather than rejected with HeaderMismatch."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "Only observable over streamable HTTP: header encoding never surfaces through the client "
            "API. Only the Mcp-Name member of the spec's 'Mcp-Name or Mcp-Param-{Name}' pair is "
            "server-validated; the SDK performs no Mcp-Param-* header-to-body comparison at all (the "
            "recorded gap on hosting:http:modern:mcp-param-mismatch-400), so the Mcp-Param decode leg "
            "is vacuous until that validation lands."
        ),
    ),
    "hosting:http:modern:mcp-param-null-absent-not-required": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#server-behavior-for-custom-headers",
        behavior=(
            "A 2026-07-28 tools/call whose annotated arguments are null or absent carries no "
            "Mcp-Param-* header for them, and the server accepts the request without expecting one."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "Only observable over streamable HTTP. The acceptance arm currently holds by "
            "construction (the server validates no Mcp-Param-* headers at all -- see "
            "hosting:http:modern:mcp-param-mismatch-400); the pin is the regression bar for "
            "when that validation lands."
        ),
    ),
    "hosting:http:modern:mcp-param-mismatch-400": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#server-behavior-for-custom-headers",
        behavior=(
            "A 2026-07-28 tools/call whose decoded Mcp-Param-{Name} header value does not match "
            "the corresponding body argument is rejected with HTTP 400 and JSON-RPC -32020 "
            "(HeaderMismatch)."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        divergence=Divergence(
            note=(
                "The server performs no Mcp-Param-* header validation: the inbound ladder "
                "compares only MCP-Protocol-Version, Mcp-Method and Mcp-Name, so a request "
                "whose decoded Mcp-Param header disagrees with the body argument is accepted "
                "and the handler runs on the body value; the same gap covers the spec's "
                "'client omits header but value is in body' reject row. The SDK has no notion "
                "of a 'recognized' param header (the inbound ladder never sees a tool schema); "
                "the pinned accept uses a header that name-matches a body argument -- the "
                "strongest candidate for any future validation -- and the unknown-header arm "
                "(a header with no corresponding body argument) is deliberately not pinned: "
                "its reject-vs-ignore consequence must be decided when validation lands."
            ),
            issue="L110",
        ),
        note="TS implements this (createMcpHandler) with no requirement id of its own.",
    ),
    "hosting:http:modern:invalid-header-chars-rejected": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#server-behavior-for-custom-headers",
        behavior=(
            "A 2026-07-28 request carrying a recognized Mcp-Param-{Name} header that contains "
            "invalid characters is rejected with HTTP 400 and JSON-RPC error -32020 HeaderMismatch."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        deferred=(
            "Not implemented in the SDK: the server never validates Mcp-Param-{Name} headers -- "
            "classify_inbound_request (src/mcp/shared/inbound.py) checks only "
            "MCP-Protocol-Version/Mcp-Method/Mcp-Name, and MCP_PARAM_HEADER_PREFIX / the "
            "x-mcp-header schema map have client-emit-only consumers (src/mcp/client/session.py), "
            "so there is no server-side notion of a 'recognized' param header, no "
            "invalid-character check, and no rejection to assert."
        ),
        note=(
            "Only observable over streamable HTTP: Mcp-Param-* are HTTP request headers. Sibling of "
            "the gap recorded on hosting:http:modern:mcp-param-mismatch-400 (issue L110): both await "
            "the same server-side Mcp-Param validation."
        ),
    ),
    "hosting:http:modern:numeric-header-comparison": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#server-validation",
        behavior=(
            "When validating integer parameter values against Mcp-Param-{Name} headers, the server "
            "compares the header value and the body value numerically rather than as strings "
            "(42.0 and 42 are considered equal)."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        deferred=(
            "Not implemented in the SDK: the server performs no Mcp-Param-{Name} header-vs-body "
            "validation (classify_inbound_request in src/mcp/shared/inbound.py checks only "
            "MCP-Protocol-Version/Mcp-Method/Mcp-Name; MCP_PARAM_HEADER_PREFIX has no server-side "
            "consumer), so there is no integer comparison -- numeric or string -- to observe; a "
            "42.0-vs-42 request is accepted only because nothing is checked."
        ),
        note=(
            "Only observable over streamable HTTP: the comparison's input is an HTTP request header. "
            "The SHOULD is the lenient arm of the Mcp-Param header-vs-body comparison whose absence "
            "is recorded on hosting:http:modern:mcp-param-mismatch-400 (issue L110)."
        ),
    ),
    "hosting:http:request-headers-in-handler": Requirement(
        source="sdk",
        behavior=(
            "A custom HTTP header sent by the client reaches the request handler through the "
            "per-request HTTP request context (ctx.request), on both the legacy session path and the "
            "2026-07-28 single-exchange path."
        ),
        transports=("streamable-http",),
        note=(
            "Only observable over streamable HTTP: stdio has no HTTP request context. No added_in: the "
            "behaviour exists on both eras. Carries phase-4 FINDING F3: the un-minted twin proposal "
            "hosting:context:web-request-headers describes the same observable; this python-neutral id "
            "is the recommended survivor of that merge."
        ),
    ),
    "hosting:http:modern-only:initialize-rejection-names-versions": Requirement(
        source="sdk",
        behavior=(
            "A server configured to serve only modern protocol revisions rejects a 2025-shaped "
            "initialize with the unsupported-protocol-version error naming its supported modern "
            "revisions in error.data.supported, instead of silently serving the 2025 era."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        deferred=(
            "Not implemented in the SDK: there is no strict/modern-only hosting posture -- "
            "StreamableHTTPSessionManager.handle_request unconditionally routes "
            "initialize-handshake-era traffic (and any request without an MCP-Protocol-Version "
            "header) to the legacy transport, and the manager exposes no option to refuse it, so the "
            "strict rejection is unconstructible."
        ),
        note=(
            "TS twin: typescript:hosting:entry:strict-rejects-legacy (createMcpHandler legacy: "
            "'reject'). The adjacent implemented behaviour -- an envelope whose protocolVersion is "
            "unsupported gets UNSUPPORTED_PROTOCOL_VERSION with data.supported -- is the classifier's "
            "rung 3 and is owned by the discover-versioning family, not this entry."
        ),
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # Client transport: streamable HTTP
    # ═══════════════════════════════════════════════════════════════════════════
    "client-transport:http:404-surfaces": Requirement(
        source="sdk",
        behavior="A 404 (session expired) on a request surfaces as an error to the caller.",
        transports=("streamable-http",),
        note="Only observable over HTTP: 404 is an HTTP status code.",
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
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2567); Mcp-Session-Id and protocol-level sessions removed, no replacement.",
    ),
    "client-transport:http:accept-header-get": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#listening-for-messages-from-the-server",
        behavior="The client GET to the MCP endpoint includes an Accept header listing text/event-stream.",
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2575); the standalone GET endpoint is replaced by the subscriptions/listen "
            "POST."
        ),
    ),
    "client-transport:http:accept-header-post": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior=(
            "Every client POST to the MCP endpoint includes an Accept header listing both application/json "
            "and text/event-stream."
        ),
        transports=("streamable-http",),
        note="Only observable over HTTP: Accept is an HTTP request header.",
    ),
    "client-transport:http:concurrent-streams": Requirement(
        source="sdk",
        behavior="Multiple concurrent POST-initiated SSE streams each deliver their response to the right caller.",
        transports=("streamable-http",),
        note="Only observable over HTTP: per-request SSE streams are HTTP-specific.",
    ),
    "client-transport:http:custom-client": Requirement(
        source="sdk",
        behavior="A caller-supplied HTTP client (and its event hooks and headers) is used for all MCP traffic.",
        transports=("streamable-http",),
        note="Only observable over HTTP: the httpx client is HTTP-specific.",
    ),
    "client-transport:http:custom-headers": Requirement(
        source="sdk",
        behavior="Caller-supplied headers are sent on every POST, GET, and DELETE to the MCP endpoint.",
        transports=("streamable-http",),
        note="Only observable over HTTP: headers are an HTTP concept.",
    ),
    "client-transport:http:json-response-parsed": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior="A Content-Type application/json response is parsed as a single JSON-RPC message.",
        transports=("streamable-http",),
        note="Only observable over HTTP: Content-Type is an HTTP response header.",
    ),
    "client-transport:http:no-reconnect-after-close": Requirement(
        source="sdk",
        behavior="After the transport is closed, no further reconnection attempts are scheduled.",
        transports=("streamable-http",),
        note="Only observable over HTTP: stream reconnection is HTTP-specific.",
    ),
    "client-transport:http:no-reconnect-after-response": Requirement(
        source="sdk",
        behavior="A POST-initiated stream that already delivered its response is not reconnected when it closes.",
        transports=("streamable-http",),
        note="Only observable over HTTP: stream reconnection is HTTP-specific.",
    ),
    "client-transport:http:protocol-version-header": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#protocol-version-header",
        behavior=(
            "After initialization, the client sends the negotiated MCP-Protocol-Version header on every "
            "subsequent HTTP request."
        ),
        transports=("streamable-http",),
        note="Only observable over HTTP: MCP-Protocol-Version is an HTTP header.",
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
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); SSE stream resumability/redelivery dropped, no replacement.",
    ),
    "client-transport:http:reconnect-post-priming": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior=(
            "A POST-initiated SSE stream that errors before delivering its response is reconnected only "
            "if a priming event (an event carrying an ID) was received on it."
        ),
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); SSE stream resumability/redelivery dropped, no replacement.",
    ),
    "client-transport:http:reconnect-retry-value": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#sending-messages-to-the-server",
        behavior="Reconnection delay honours the server-provided SSE retry value when one was sent.",
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); SSE stream resumability/redelivery dropped, no replacement.",
    ),
    "client-transport:http:resume-stream-api": Requirement(
        source="sdk",
        behavior=(
            "The client can capture a resumption token, reconnect with the same session id, and receive "
            "the notifications it missed."
        ),
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); SSE stream resumability/redelivery dropped, no replacement.",
    ),
    "client-transport:http:session-stored": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior=(
            "The Mcp-Session-Id returned by initialize is stored by the client transport and sent on "
            "every subsequent request."
        ),
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2567); Mcp-Session-Id and protocol-level sessions removed, no replacement.",
    ),
    "client-transport:http:sse-405-tolerated": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#listening-for-messages-from-the-server",
        behavior="Opening the standalone GET SSE stream tolerates a 405 response without failing the connection.",
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2575); the standalone GET endpoint is replaced by the subscriptions/listen "
            "POST."
        ),
    ),
    "client-transport:http:terminate-405-ok": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior="Session termination succeeds without error if the server answers 405 (termination unsupported).",
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2567); session DELETE removed with Mcp-Session-Id, no replacement.",
    ),
    "client-transport:http:body-derived-headers": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#standard-request-headers",
        behavior=(
            "An envelope-bearing request body yields MCP-Protocol-Version, Mcp-Method, and (for tools/call) "
            "Mcp-Name headers on the outgoing HTTP request; a body without the envelope yields none."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note="Only observable over streamable HTTP: headers are derived from the body envelope at the transport seam.",
    ),
    "client-transport:http:mcp-name-base64-sentinel": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#standard-request-headers",
        behavior=(
            "A tools/call for a tool whose name is not header-safe carries the Mcp-Name header "
            "in the =?base64?...?= sentinel form while the body keeps the literal name, and the "
            "round trip completes."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note="Only observable over streamable HTTP: the header is derived at the transport seam.",
    ),
    "client-transport:http:custom-param-headers": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#custom-headers-from-tool-parameters",
        behavior=(
            "On a tools/call, a client mirrors each argument annotated with x-mcp-header in the tool's "
            "inputSchema into an Mcp-Param-<name> header -- string as-is, integer as decimal, boolean as "
            "true/false, base64-sentinel-wrapped when not header-safe -- omitting null or absent arguments and "
            "never mirroring unannotated parameters. The schema is taken from the tool's last list_tools entry; "
            "a tool the client never listed emits no Mcp-Param-* headers."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note="Only observable over streamable HTTP: headers are derived from the cached tool schema at the seam.",
    ),
    "client-transport:http:custom-param-headers:sentinel-collision-escaped": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#value-encoding",
        behavior=(
            "A plain-ASCII argument value that itself matches the =?base64?...?= sentinel "
            "pattern is base64-wrapped when mirrored into its Mcp-Param-* header, while the "
            "body keeps the literal value."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note="Only observable over streamable HTTP: headers are derived from the cached tool schema at the seam.",
    ),
    "client-transport:http:custom-param-headers:refresh-and-retry-on-reject": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#client-behavior",
        behavior=(
            "When a server rejects a tools/call because required custom Mcp-Param-* headers "
            "are missing, the client refetches tools/list to obtain the current inputSchema "
            "and retries the original request with the appropriate headers."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        deferred=(
            "Not implemented in the SDK: the client has no recovery path for a header-rejection "
            "error -- call_tool issues a single request and raises the JSON-RPC error to the "
            "caller; no handler refetches tools/list and retries with the appropriate headers."
        ),
        note=(
            "Only observable over streamable HTTP: the trigger is an HTTP-layer HeaderMismatch "
            "rejection and the retried request's Mcp-Param-* headers are wire artifacts."
        ),
    ),
    "client-transport:http:vendor-name-param-header": Requirement(
        source="sdk",
        behavior=(
            "A vendor request type declaring name_param mirrors that wire-params key into the Mcp-Name "
            "header of its outgoing HTTP request, with no client-side registration of the method."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "SDK mechanism honouring the per-extension Mcp-Name requirements (e.g. SEP-2663 mandates the "
            "header for tasks/*); only observable over streamable HTTP, where headers exist."
        ),
    ),
    "client-transport:http:stateless-ignores-session-id": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/transports/streamable-http#standard-request-headers",
        behavior=(
            "A pinned client never echoes a server-issued Mcp-Session-Id and never opens the standalone "
            "GET stream or the closing DELETE: the recorded wire is POST-only."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note="Only observable over streamable HTTP: session-id, GET stream and DELETE are streamable-HTTP mechanics.",
        deferred="defensive against a misbehaving peer; covered by a tests/client/ unit test",
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
        note="OAuth is HTTP-only.",
    ),
    "client-auth:401-triggers-flow": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#protected-resource-metadata-discovery-requirements",
        behavior="A 401 on a request triggers the OAuth authorization flow once.",
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:403-scope-upgrade": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#step-up-authorization-flow",
        behavior="A 403 with WWW-Authenticate triggers a scope-upgrade authorization attempt.",
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:stepup:scope-union": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#step-up-authorization-flow",
        behavior=(
            "On a 403 insufficient_scope step-up, the re-authorization request carries the union of the "
            "previously requested scopes and the newly challenged scopes (SEP-2350)."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:stepup:retry-cap": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#step-up-authorization-flow",
        behavior=(
            "Step-up re-authorization is bounded per request send: one re-authorization and one "
            "retry, after which a further insufficient_scope 403 on the retried request "
            "surfaces to the caller as an error without another authorization attempt."
        ),
        transports=("streamable-http",),
        note=(
            "OAuth is HTTP-only. The bound is structural -- the auth flow performs at most one "
            "step-up before its generator ends -- not a configurable retry count; the surfaced "
            "error is the transport's INTERNAL_ERROR stand-in for a non-2xx final response. "
            "Cross-request attempt tracking is the separate deferred "
            "client-auth:stepup:attempt-tracking."
        ),
    ),
    "client-auth:stepup:get-stream-403": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#step-up-authorization-flow",
        behavior=(
            "A 403 insufficient_scope challenge on the standalone GET stream open receives the "
            "same step-up handling as the POST path: the scope union is re-authorized once and "
            "the stream is established on the retried GET with the upgraded token."
        ),
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note=(
            "OAuth is HTTP-only. The standalone GET stream is a 2025-11-25 transport mechanism "
            "removed at 2026-07-28; the auth suite's legacy-mode connect is its natural home. "
            "The uniformity is structural (the OAuth provider wraps every request the transport "
            "issues), but the GET leg's choreography is pinned because a failed step-up there "
            "would otherwise vanish into the stream's silent reconnect loop."
        ),
    ),
    "client-auth:stepup:attempt-tracking": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#step-up-authorization-flow",
        behavior=(
            "The client tracks scope-upgrade attempts across request sends to avoid repeated "
            "failures for the same resource and operation combination."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only. The per-send bound is client-auth:stepup:retry-cap.",
        deferred=(
            "Not implemented in the SDK: the client OAuth provider keeps no cross-request memory "
            "of scope-upgrade attempts. The 403 insufficient_scope branch "
            "(src/mcp/client/auth/oauth2.py:704-734) performs one inline step-up per send with no "
            "attempt counter and no (resource, operation) key, and OAuthContext (oauth2.py:98) "
            "carries no field recording prior step-up failures, so a second send for the same "
            "resource and operation re-attempts the upgrade unconditionally. The per-send "
            '"repeated 403s do not loop" half of this spec line is client-auth:403-scope-upgrade.'
        ),
    ),
    "client-auth:as-metadata-discovery:priority-order": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#authorization-server-metadata-discovery",
        behavior=(
            "The client discovers authorization-server metadata by trying, in order, the OAuth "
            "path-inserted, OIDC path-inserted, and OIDC path-appended well-known URLs (with the "
            "root-path forms when the issuer URL has no path)."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:as-metadata-discovery:issuer-validation": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#authorization-server-metadata-discovery",
        behavior=(
            "The client rejects authorization-server metadata whose issuer does not match the URL the "
            "metadata was retrieved from (RFC 8414 section 3.3 / SEP-2468)."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:authorize:error-surfaces": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#authorization-flow-steps",
        behavior=(
            "An OAuth error redirect from the authorize endpoint aborts the flow before any token "
            "request is issued, surfacing as an error to the caller."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
        divergence=Divergence(
            note=(
                "The callback contract has no error form, so the client surfaces 'No authorization code "
                "received' rather than the redirect's `error`/`error_description` values."
            ),
        ),
    ),
    "client-auth:scope:offline-access-gate": Requirement(
        source="sdk",
        behavior=(
            "When the authorization server's metadata advertises offline_access in scopes_supported and "
            "the client uses the refresh_token grant, offline_access is appended to the requested scope "
            "and prompt=consent is added to the authorize request."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:bearer-header:every-request": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#token-requirements",
        behavior=(
            "Once authorized, the client sends the bearer token in the Authorization header on every HTTP "
            "request to the MCP server, never in the query string."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:cimd": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#client-id-metadata-documents",
        behavior="The client can use a client-ID metadata document URL as its OAuth client_id instead of registration.",
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:client-credentials": Requirement(
        source="sdk",
        behavior=(
            "A client-credentials provider obtains a token without user interaction and the resulting "
            "bearer token authorizes subsequent requests."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:dcr:registration-rejected-error": Requirement(
        source="sdk",
        behavior=(
            "A 400 from the registration endpoint surfaces to the caller as an OAuthRegistrationError "
            "carrying the status and the server's RFC 7591 error body."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:dcr": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#dynamic-client-registration",
        behavior=(
            "The client performs dynamic client registration against the authorization server when no "
            "client_id is preconfigured."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:dcr:app-type-heuristic": Requirement(
        source=(
            f"{SPEC_2026_BASE_URL}"
            "/basic/authorization/client-registration#application-type-and-redirect-uri-constraints"
        ),
        behavior=(
            "When the client metadata does not set application_type, dynamic client "
            "registration derives it from the redirect URIs: a loopback host or custom URI "
            "scheme yields 'native', otherwise 'web' (SEP-837)."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "OAuth is HTTP-only. The spec MUST (always send an application_type) IS satisfied "
            "at this pin: OAuthClientMetadata defaults the field to 'native' and every "
            "registration body carries it, pinned incidentally by the "
            "client-auth:dcr:grant-types-default body snapshot. Only the derive-from-redirect-"
            "URIs strategy for the 'web' SHOULD is unimplemented; a web-app consumer sets "
            "application_type='web' explicitly and it is transmitted verbatim."
        ),
        deferred=(
            "Not implemented in the SDK: application_type is a static model default ('native') "
            "on OAuthClientMetadata (src/mcp/shared/auth.py); no code path inspects the "
            "redirect URIs to choose between 'native' and 'web'."
        ),
    ),
    "client-auth:dcr:grant-types-default": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/authorization#refresh-tokens",
        behavior=(
            "When the client metadata does not set grant_types, the dynamic-registration "
            "request carries ['authorization_code', 'refresh_token'] so the authorization "
            "server may issue refresh tokens (SEP-2207); a consumer-set grant_types is sent "
            "verbatim, never rewritten."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "OAuth is HTTP-only. A SHOULD. Python implements the default on the "
            "OAuthClientMetadata model (a field default), not in registration code, so it is "
            "present from construction -- wire-observably identical to injecting it at "
            "registration time, which is what the registration body pins."
        ),
    ),
    "client-auth:as-binding:reregister": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/authorization/client-registration#authorization-server-binding",
        behavior=(
            "Stored client credentials are bound to the issuer that registered them; when the "
            "authorization server changes, the client discards them and re-registers with the "
            "new authorization server (SEP-2352)."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:as-binding:no-cred-reuse": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/authorization/client-registration#authorization-server-binding",
        behavior=(
            "When the authorization server changes, the client never reuses credentials from "
            "the previous authorization server: the stale client_id reaches neither the "
            "authorize nor the token endpoint (SEP-2352)."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:invalid-client-clears-all": Requirement(
        source="sdk",
        behavior=(
            "An invalid-client or unauthorized-client error during authorization invalidates all stored credentials."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
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
        note="OAuth is HTTP-only.",
    ),
    "client-auth:pkce:refuse-if-unsupported": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#authorization-code-protection",
        behavior=(
            "The client refuses to proceed when the authorization server's metadata does not include "
            "code_challenge_methods_supported, since PKCE support cannot be verified."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
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
        note="OAuth is HTTP-only.",
    ),
    "client-auth:pre-registration": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#preregistration",
        behavior=(
            "A client with statically preconfigured credentials skips dynamic registration and uses them directly."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:private-key-jwt": Requirement(
        source="sdk",
        behavior="The client can authenticate the client-credentials grant with a signed JWT assertion.",
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:prm-discovery:fallback-order": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#protected-resource-metadata-discovery-requirements",
        behavior=(
            "The client uses resource_metadata from WWW-Authenticate when present, then falls back to the "
            "well-known protected-resource locations in the documented order."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:prm-discovery:no-prm-fallback": Requirement(
        source="sdk",
        behavior=(
            "When every protected-resource metadata probe fails, the client falls back to discovering "
            "authorization-server metadata directly at the MCP server's origin (the legacy 2025-03-26 path) "
            "rather than aborting."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:prm-resource-mismatch": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#authorization-server-location",
        behavior=(
            "The client refuses to proceed when the protected-resource metadata's resource field does not "
            "match the server URL it is connecting to."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:refresh:rotation-handling": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/authorization#refresh-tokens",
        behavior=(
            "On a refresh-token exchange, a new refresh_token in the response replaces the "
            "stored one, and a response that omits refresh_token leaves the stored one in "
            "place -- the client never assumes a refresh token will be issued "
            "(RFC 6749 section 6 / SEP-2207)."
        ),
        transports=("streamable-http",),
        note=(
            "OAuth is HTTP-only. No added_in: the replace/preserve mechanics are RFC 6749 "
            "section 6 client behaviour that predates the 2026 Refresh Tokens section restating "
            "them (the add plan classifies this entry era PRE-EXISTING), and the auth tests "
            "bypass the connect fixture so era fields drive no cells. The follow-on claim -- "
            "the NEXT refresh presents the rotated token -- is real-time-bound at this pin: a "
            "token that is already expired when its refresh response arrives is not refreshed "
            "again on the same request; the request goes out unauthenticated and 401s into a "
            "full re-authorization (oauth2.py sends at most one refresh per request and only "
            "attaches a bearer it considers valid), so a second same-connection refresh cannot "
            "be driven without wall-clock waits. The tests therefore pin replacement and "
            "preservation at the storage/wire seam of a single refresh."
        ),
    ),
    "client-auth:refresh:transparent": Requirement(
        source="sdk",
        behavior=(
            "An access token the client considers expired is transparently refreshed before the next "
            "request, using the stored refresh token; the refresh request includes the resource indicator "
            "and the new token is persisted."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:resource-parameter": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#resource-parameter-implementation",
        behavior=(
            "The client includes the canonical server URI as the resource parameter in both the "
            "authorization request and the token request."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:scope-selection:priority": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#scope-selection-strategy",
        behavior=(
            "Client selects requested scope from the WWW-Authenticate scope param if present; otherwise "
            "uses scopes_supported from the PRM document; otherwise omits scope."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
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
        note="OAuth is HTTP-only.",
    ),
    "client-auth:iss:mismatch-reject": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/authorization#authorization-response-validation",
        behavior=(
            "The client validates the RFC 9207 iss authorization-response parameter against the "
            "authorization server issuer (simple string comparison) and rejects a mismatch (SEP-2468)."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:iss:match": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/authorization#authorization-response-validation",
        behavior=(
            "When the authorization server's metadata advertises "
            "authorization_response_iss_parameter_supported and the callback's iss equals the "
            "recorded metadata issuer, the client proceeds to redeem the authorization code "
            "(RFC 9207 validation table row 1)."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:iss:no-normalize": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/authorization#authorization-response-validation",
        behavior=(
            "The iss comparison is simple string comparison (RFC 3986 section 6.2.1): a value "
            "differing from the recorded issuer only by a trailing slash is rejected as a "
            "mismatch -- no scheme or host case folding, default-port elision, trailing-slash, "
            "or percent-encoding normalization is applied before comparison."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "OAuth is HTTP-only. The comparison is a single string inequality; the test pins the "
            "trailing-slash arm as the representative normalization class."
        ),
    ),
    "client-auth:iss:supported-missing-reject": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/authorization#authorization-response-validation",
        behavior=(
            "When the authorization server's metadata advertises "
            "authorization_response_iss_parameter_supported: true and the callback carries no "
            "iss, the client rejects the authorization response before redeeming the code "
            "(RFC 9207 validation table row 2)."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:iss:unadvertised-proceed": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/authorization#authorization-response-validation",
        behavior=(
            "When the authorization server's metadata does not advertise "
            "authorization_response_iss_parameter_supported and the callback carries no iss, "
            "the client proceeds with the code exchange (RFC 9207 validation table row 4)."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:iss:unadvertised-present-validated": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/authorization#authorization-response-validation",
        behavior=(
            "A present iss is validated against the recorded issuer regardless of metadata "
            "advertisement (RFC 9207 validation table row 3, where this specification "
            "deliberately exceeds RFC 9207's local-policy provision): a matching iss proceeds "
            "and a mismatching iss is rejected."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "OAuth is HTTP-only. Covered by two tests: the match half directly, and the "
            "mismatch half by the client-auth:iss:mismatch-reject test, which drives a "
            "mismatched iss against the suite's unadvertising authorization server."
        ),
    ),
    "client-auth:iss:error-response-validated": Requirement(
        source=f"{SPEC_2026_BASE_URL}/basic/authorization#authorization-response-validation",
        behavior=(
            "iss validation applies equally to error responses: a mismatched iss on an error "
            "callback is rejected before the flow acts on the response, and on mismatch the "
            "client must not act on or display error, error_description, or error_uri."
        ),
        added_in="2026-07-28",
        transports=("streamable-http",),
        note=(
            "OAuth is HTTP-only. The non-surfacing half holds by construction: the callback "
            "contract (AuthorizationCodeResult) carries no error fields, so those values never "
            "enter the SDK; the test pins the observable half -- the iss mismatch is raised in "
            "preference to the missing-authorization-code failure."
        ),
    ),
    "client-auth:token-endpoint-auth-method": Requirement(
        source="sdk",
        behavior="The client authenticates to the token endpoint using the auth method established at registration.",
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:token-error:machine-readable-code": Requirement(
        source="sdk",
        behavior=(
            "An RFC 6749 error response from the token endpoint (e.g. invalid_grant, "
            "invalid_client, on either the authorization-code exchange or a refresh) surfaces "
            "to the caller as a typed OAuth error carrying the wire error code as a "
            "machine-readable field, not only embedded in the message text."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only. The weak testable sibling is client-auth:token:error-surfaces.",
        deferred=(
            "Not implemented in the SDK: OAuthTokenError (src/mcp/client/auth/exceptions.py) "
            "carries only a message string; the token-response handler embeds the RFC 6749 "
            "error body in an f-string and the refresh-response handler clears tokens without "
            "reading the body (src/mcp/client/auth/oauth2.py), so there is no machine-readable "
            "error code for a caller to branch on."
        ),
    ),
    "client-auth:token:error-surfaces": Requirement(
        source="sdk",
        behavior=(
            "A non-2xx response from the token endpoint on the authorization-code exchange "
            "aborts the flow and surfaces to the caller as an error naming the HTTP status; "
            "the flow does not loop, and no request is ever sent with a bearer token."
        ),
        transports=("streamable-http",),
        note=(
            "OAuth is HTTP-only. Completes the endpoint error-surfaces family alongside "
            "client-auth:authorize:error-surfaces and "
            "client-auth:dcr:registration-rejected-error; the machine-readable half is "
            "client-auth:token-error:machine-readable-code (deferred)."
        ),
    ),
    "client-auth:token-provenance": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#token-handling",
        behavior=(
            "The client sends the MCP server only tokens issued by that server's authorization server, "
            "never tokens obtained elsewhere."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
        deferred=(
            "Untestable negative through the public API: there is no path to inject a token obtained "
            "elsewhere into the auth provider's state, so the absence cannot be observed end to end."
        ),
    ),
    "client-auth:identity-assertion": Requirement(
        source="sdk",
        behavior=(
            "The identity-assertion provider (SEP-990) presents an enterprise IdP-issued ID-JAG to the MCP "
            "authorization server via the RFC 7523 jwt-bearer grant, with no authorize or registration step, "
            "and the issued bearer token authorizes subsequent requests."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:identity-assertion:assertion-callback": Requirement(
        source="sdk",
        behavior=(
            "The identity-assertion provider sources the ID-JAG from its async assertion_provider callback, "
            "invoked with the authorization server's issuer as audience and the MCP server's resource "
            "identifier, and sends it as `assertion` on the RFC 7523 jwt-bearer request."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:identity-assertion:issuer-pinning": Requirement(
        source="sdk",
        behavior=(
            "The identity-assertion provider's authorization server is configuration: metadata is "
            "fetched only from the configured issuer's RFC 8414 well-known, the resource server is "
            "never consulted for AS selection, and the ID-JAG and client secret are not sent unless "
            "that metadata validates."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:identity-assertion:disabled-rejected": Requirement(
        source="sdk",
        behavior=(
            "When the authorization server has the identity-assertion grant disabled, the token endpoint "
            "rejects it with unsupported_grant_type and the connection fails rather than issuing a token."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:identity-assertion:invalid-assertion": Requirement(
        source="sdk",
        behavior=(
            "A jwt-bearer request whose ID-JAG the authorization server rejects surfaces as an OAuth error "
            "and the connection fails rather than proceeding with a bearer token."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "client-auth:identity-assertion:metadata-advertised": Requirement(
        source="sdk",
        behavior=(
            "When the identity-assertion grant is enabled, the authorization-server metadata advertises the "
            "jwt-bearer grant type and the id-jag grant profile in authorization_grant_profiles_supported."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    # ═══════════════════════════════════════════════════════════════════════════
    # stdio transport
    # ═══════════════════════════════════════════════════════════════════════════
    "transport:stdio:clean-shutdown": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#shutdown",
        behavior="Closing the client transport closes the child process's stdin and the server exits cleanly.",
        transports=("stdio",),
        note="Only observable over stdio: child-process lifecycle is stdio-specific.",
    ),
    "transport:stdio:stream-purity": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#stdio",
        behavior=(
            "Nothing that is not a valid MCP message is written to the server's stdout, and nothing that "
            "is not a valid MCP message is written to its stdin."
        ),
        transports=("stdio",),
        note="Only observable over stdio: stdin/stdout purity is stdio-specific.",
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
        note="Only observable over stdio: newline-delimited framing is stdio-specific.",
    ),
    "transport:stdio:shutdown-escalation": Requirement(
        source=f"{SPEC_BASE_URL}/basic/lifecycle#stdio",
        behavior=(
            "If the server process does not exit after stdin is closed, the client transport terminates "
            "it (and kills it if still alive) after a grace period."
        ),
        transports=("stdio",),
        note="Only observable over stdio: child-process lifecycle is stdio-specific.",
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
        note="Only observable over stdio: stderr is a child-process stream.",
    ),
    "transport:stdio:dual-era-serving": Requirement(
        source="sdk",
        behavior=(
            "A stdio server serves a plain legacy client via initialize and an "
            "auto-negotiating client at 2026-07-28 via server/discover, each on its own "
            "connection against the same factory, over a real child-process pipe."
        ),
        added_in="2026-07-28",
        transports=("stdio",),
        deferred=(
            "Not implemented in the SDK: the stdio stream-loop server cannot serve 2026-era "
            "requests -- the legacy loop's init gate (src/mcp/server/runner.py) rejects "
            "envelope-bearing requests with INVALID_PARAMS because a pinned-2026 client never "
            "sends initialize, and nothing on the stdio path wires Connection.from_envelope, "
            "so a dual-era stdio factory is unconstructible."
        ),
        note=(
            "stdio-only by definition: the dual-era HTTP analogue is the session manager's "
            "header routing, pinned by hosting:http:modern:legacy-fallthrough and "
            "lifecycle:version:dual-era-precedence."
        ),
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
        note="Exercises both HTTP transports side by side; not applicable to stdio.",
    ),
    "flow:compat:streamable-then-sse-fallback": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#backwards-compatibility",
        behavior=(
            "When a streamable HTTP initialize fails with 400, 404, or 405, falling back to the legacy "
            "SSE client transport against the same server connects successfully."
        ),
        transports=("streamable-http", "sse"),
        note="Exercises the HTTP-to-SSE fallback path; not applicable to stdio.",
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
        removed_in="2026-07-28",
        superseded_by="mrtr:multi-round:complete",
        note=(
            "removed in 2026-07-28 (SEP-2322); sequential elicitation steps become multiple MRTR "
            "input_required rounds before completion."
        ),
        arm_exclusions=(ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),),
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
        removed_in="2026-07-28",
        note=(
            "removed in 2026-07-28 (SEP-2575); the standalone GET stream and session initialization are both gone, no "
            "replacement."
        ),
    ),
    "flow:elicitation:url-required-then-retry": Requirement(
        source=f"{SPEC_BASE_URL}/client/elicitation#url-elicitation-required-error",
        behavior=(
            "A tool call rejected with the URL-elicitation-required error can be retried successfully "
            "after the client completes the URL flow and the server announces completion."
        ),
        removed_in="2026-07-28",
        superseded_by="mrtr:url-elicitation:no-32042-on-2026",
        note=(
            "removed in 2026-07-28 (SEP-2322); the -32042 + elicitation/complete flow is replaced by the MRTR "
            "input_required/retry loop."
        ),
        arm_exclusions=(ArmExclusion(reason="requires-session", transport="streamable-http-stateless"),),
    ),
    "flow:multi-client:stateful-isolation": Requirement(
        source="sdk",
        behavior=(
            "Independent clients connected to one stateful server each receive a distinct session and "
            "only the notifications produced by their own requests."
        ),
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2567); per-client Mcp-Session-Id sessions removed, no replacement.",
    ),
    "flow:oauth:authorization-code-roundtrip": Requirement(
        source=f"{SPEC_BASE_URL}/basic/authorization#authorization-flow-steps",
        behavior=(
            "Connecting to a protected server walks the authorization-code flow end to end: the first "
            "attempt requires authorization, the code is exchanged, and a subsequent connection succeeds."
        ),
        transports=("streamable-http",),
        note="OAuth is HTTP-only.",
    ),
    "flow:resume:tool-call-resumption-token": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#resumability-and-redelivery",
        behavior=(
            "A tool call interrupted mid-stream is transparently resumed by the client transport using "
            "the last-seen event id, delivering only the remaining notifications and the final result."
        ),
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2575); SSE stream resumability/redelivery dropped, no replacement.",
    ),
    "flow:session:terminate-then-reconnect": Requirement(
        source=f"{SPEC_BASE_URL}/basic/transports#session-management",
        behavior=("After terminating a session, a fresh connection obtains a new session id and operations succeed."),
        transports=("streamable-http",),
        removed_in="2026-07-28",
        note="removed in 2026-07-28 (SEP-2567); session DELETE removed with Mcp-Session-Id, no replacement.",
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


def cell_id(transport: Transport, version: SpecVersion, *, spec_versions: Sequence[SpecVersion] = SPEC_VERSIONS) -> str:
    """Return the pytest node-id suffix for a (transport, spec_version) cell.

    While the active matrix has a single spec version, the suffix is just the transport name so
    existing node ids stay byte-identical; once a second version is on the axis the suffix becomes
    ``transport-version``.
    """
    return transport if len(spec_versions) == 1 else f"{transport}-{version}"


def compute_cells(
    requirements: Sequence[Requirement],
    *,
    spec_versions: Sequence[SpecVersion] = SPEC_VERSIONS,
    transports: Sequence[Transport] = CONNECTABLE_TRANSPORTS,
) -> list[Any]:
    """Compute the (transport, spec_version) parametrization cells for a test.

    Stacked ``@requirement`` decorators contribute multiple entries; the cells emitted are the
    INTERSECTION across all of them: a cell is dropped if it falls outside any requirement's
    ``[added_in, removed_in)`` window or matches any requirement's ``arm_exclusions``. An empty
    ``requirements`` sequence yields the full transport x spec-version grid.

    ``Requirement.transports`` is intentionally NOT consulted -- it is descriptive metadata about
    where a behaviour is observable, not a cell filter (only ``arm_exclusions`` / ``added_in`` /
    ``removed_in`` drive cell generation).

    Returns a list of ``pytest.param((transport, version), id=..., marks=...)`` values for use as
    ``metafunc.parametrize`` argvalues.
    """
    cells: list[Any] = []
    for version in spec_versions:
        version_ordinal = KNOWN_PROTOCOL_VERSIONS.index(version)
        for transport in sorted(transports):
            if transport in TRANSPORT_SPEC_VERSIONS and version not in TRANSPORT_SPEC_VERSIONS[transport]:
                continue
            # Requirement.transports is descriptive metadata only and does not filter cells.
            if any(
                (req.added_in is not None and version_ordinal < KNOWN_PROTOCOL_VERSIONS.index(req.added_in))
                or (req.removed_in is not None and version_ordinal >= KNOWN_PROTOCOL_VERSIONS.index(req.removed_in))
                for req in requirements
            ):
                continue
            if any(
                (ex.transport is None or ex.transport == transport)
                and (ex.spec_version is None or ex.spec_version == version)
                for req in requirements
                for ex in req.arm_exclusions
            ):
                continue
            matched_failure = next(
                (
                    kf
                    for req in requirements
                    for kf in req.known_failures
                    if (kf.transport is None or kf.transport == transport)
                    and (kf.spec_version is None or kf.spec_version == version)
                ),
                None,
            )
            marks = [pytest.mark.xfail(reason=matched_failure.note, strict=True)] if matched_failure else ()
            cells.append(
                pytest.param(
                    (transport, version),
                    id=cell_id(transport, version, spec_versions=spec_versions),
                    marks=marks,
                )
            )
    return cells
