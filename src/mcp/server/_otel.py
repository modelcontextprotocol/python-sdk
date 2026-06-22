from __future__ import annotations

from typing import Any

from opentelemetry.trace import SpanKind, StatusCode
from pydantic import ValidationError

from mcp.server.context import CallNext, HandlerResult, ServerMiddleware, ServerRequestContext
from mcp.shared._otel import extract_trace_context, otel_span
from mcp.shared.exceptions import MCPError


class OpenTelemetryMiddleware(ServerMiddleware[Any]):
    """Context-tier middleware that wraps each inbound message in an OpenTelemetry span.

    Span name `"MCP handle <method> [<target>]"`, `mcp.method.name` attribute, W3C
    trace context extracted from `params._meta` (SEP-414), and an ERROR status if
    the handler raises. Requests and notifications both get a span;
    `jsonrpc.request.id` is set only when `ctx.request_id` is present (notifications
    have none).
    """

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        name = ctx.params.get("name") if ctx.params else None
        target = name if isinstance(name, str) else None

        attributes: dict[str, Any] = {"mcp.method.name": ctx.method}
        if ctx.request_id is not None:
            attributes["jsonrpc.request.id"] = str(ctx.request_id)

        with otel_span(
            name=f"MCP handle {ctx.method}{f' {target}' if target else ''}",
            kind=SpanKind.SERVER,
            attributes=attributes,
            context=extract_trace_context(ctx.meta),
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                return await call_next(ctx)
            except MCPError as e:
                span.set_status(StatusCode.ERROR, e.error.message)
                raise
            except ValidationError:
                # Mirror the sanitized wire response; pydantic messages carry client input.
                span.set_status(StatusCode.ERROR, "Invalid request parameters")
                raise
            except Exception as e:
                span.record_exception(e)
                span.set_status(StatusCode.ERROR, str(e))
                raise
