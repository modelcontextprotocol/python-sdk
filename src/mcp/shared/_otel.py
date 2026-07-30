"""OpenTelemetry helpers for MCP.

`opentelemetry-api` is a hard dependency, but it is imported here on the first
span rather than at module import: every SDK entry point (client and server,
over every transport) routes messages through this module, and a tracer that is
a no-op until an exporter is installed should not add its import cost to
`import mcp` or to a process that never emits a span. The API modules and the
tracer are resolved once and cached in module globals; nothing is re-imported
per message.
"""

from __future__ import annotations

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from opentelemetry.context import Context
    from opentelemetry.trace import SpanKind, Tracer
    from opentelemetry.trace.span import Span

SpanKindName = Literal["client", "server"]
"""Name of an `opentelemetry.trace.SpanKind` member, resolved once the API loads.

Callers pass the name (or a `SpanKind` member directly) so they need not import
opentelemetry themselves.
"""

# The tracer used for every MCP span: `None` until the first span, then the
# tracer OpenTelemetry late-binds to the global provider (so an exporter
# configured after import still lights spans up). Assigning it directly is
# the seam tests use to scope spans to a capturing provider.
_tracer: Tracer | None = None

# The `opentelemetry.trace` / `opentelemetry.propagate` modules, imported
# together on first use by `_load` (typed `Any`: they are modules).
_trace: Any = None
_propagate: Any = None


def _load() -> Any:
    """Import the OpenTelemetry API, cache it, and return `opentelemetry.trace`.

    Deferred to first use purely for import time (see the module docstring);
    every later call is served from the module-level cache by `_api`.
    """
    global _trace, _propagate
    from opentelemetry import propagate, trace

    _propagate = propagate
    _trace = trace
    return trace


def _api() -> Any:
    """The `opentelemetry.trace` module, importing the OTel API on first use."""
    return _trace if _trace is not None else _load()


def _get_tracer() -> Tracer:
    """The MCP tracer, created from the global provider on the first span."""
    global _tracer
    tracer = _tracer
    if tracer is None:
        tracer = _tracer = _api().get_tracer("mcp-python-sdk")
    return tracer


@contextmanager
def otel_span(
    name: str,
    *,
    kind: SpanKindName | SpanKind,
    attributes: dict[str, Any] | None = None,
    context: Context | None = None,
    record_exception: bool = True,
    set_status_on_exception: bool = True,
) -> Generator[Span]:
    """Create an OTel span."""
    tracer = _get_tracer()
    if kind == "client":
        span_kind: SpanKind = _api().SpanKind.CLIENT
    elif kind == "server":
        span_kind = _api().SpanKind.SERVER
    else:
        span_kind = kind
    with tracer.start_as_current_span(
        name,
        kind=span_kind,
        attributes=attributes,
        context=context,
        record_exception=record_exception,
        set_status_on_exception=set_status_on_exception,
    ) as span:
        yield span


def set_span_error(span: Span, description: str | None = None) -> None:
    """Mark `span` as errored (`StatusCode.ERROR`), with an optional description."""
    span.set_status(_api().StatusCode.ERROR, description)


def inject_trace_context(meta: dict[str, Any]) -> None:
    """Inject W3C trace context (traceparent/tracestate) into a `_meta` dict."""
    _api()
    _propagate.inject(meta)


def extract_trace_context(meta: Mapping[str, Any] | None) -> Context | None:
    """Extract W3C trace context from a `_meta` dict.

    Returns `None` when the carrier is absent, malformed, or carries no
    valid `traceparent`, so callers fall through to ambient parenting; an
    explicit empty `Context` would orphan the span instead of nesting under
    the current one.
    """
    if not meta:
        return None
    trace = _api()
    try:
        ctx = _propagate.extract(meta)
    except (ValueError, TypeError):
        return None
    if not trace.get_current_span(ctx).get_span_context().is_valid:
        return None
    return ctx
