from __future__ import annotations

from typing import Any

from opentelemetry.trace import SpanKind, StatusCode
from pydantic import ValidationError

from mcp.server.context import CallNext, HandlerResult, ServerMiddleware, ServerRequestContext
from mcp.shared._otel import extract_trace_context, otel_span
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult


class OpenTelemetryMiddleware(ServerMiddleware[Any]):
    """Context-tier middleware that wraps each inbound message in an OpenTelemetry span.

    Span name `"<method> [<target>]"`, `mcp.method.name` attribute, W3C trace context extracted from
    `params._meta` (SEP-414), and an ERROR status if the handler raises. Requests and notifications both get a span;
    `jsonrpc.request.id` is set only when `ctx.request_id` is present (notifications have none).

    Tool and prompt operations additionally carry the GenAI semantic-convention attributes `gen_ai.tool.name` /
    `gen_ai.prompt.name`, and `gen_ai.operation.name` is set to `execute_tool` for `tools/call`. Failures set
    `error.type` and `rpc.response.status_code` to the JSON-RPC error code, or `error.type` to `tool_error` for a
    `tools/call` result carrying `is_error`.
    """

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        name = ctx.params.get("name") if ctx.params else None
        target = name if isinstance(name, str) else None

        attributes: dict[str, Any] = {
            "mcp.method.name": ctx.method,
            "mcp.protocol.version": ctx.protocol_version,
        }
        if ctx.request_id is not None:
            attributes["jsonrpc.request.id"] = str(ctx.request_id)

        if target is not None:
            if ctx.method == "tools/call":
                attributes["gen_ai.operation.name"] = "execute_tool"
                attributes["gen_ai.tool.name"] = target
            elif ctx.method == "prompts/get":
                attributes["gen_ai.prompt.name"] = target

        with otel_span(
            name=f"{ctx.method}{f' {target}' if target else ''}",
            kind=SpanKind.SERVER,
            attributes=attributes,
            context=extract_trace_context(ctx.meta),
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                result = await call_next(ctx)
            except MCPError as e:
                code = str(e.error.code)
                span.set_attributes({"error.type": code, "rpc.response.status_code": code})
                span.set_status(StatusCode.ERROR, e.error.message)
                raise
            except ValidationError:
                # Mirror the sanitized wire response; pydantic messages carry client input.
                span.set_attribute("error.type", "ValidationError")
                span.set_status(StatusCode.ERROR, "Invalid request parameters")
                raise
            except Exception as e:
                span.set_attribute("error.type", type(e).__qualname__)
                span.record_exception(e)
                span.set_status(StatusCode.ERROR, str(e))
                raise
            if ctx.method == "tools/call":
                match result:
                    case CallToolResult(is_error=True) | {"isError": True} | {"is_error": True}:
                        span.set_attribute("error.type", "tool_error")
                        span.set_status(StatusCode.ERROR)
                    case _:
                        pass
            return result
