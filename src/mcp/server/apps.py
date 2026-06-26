"""MCP Apps extension (`io.modelcontextprotocol/ui`).

MCP Apps lets a tool carry a reference to an interactive UI: the tool's
`_meta.ui.resourceUri` points at a `ui://` resource (an HTML document served
with the `text/html;profile=mcp-app` MIME type) that the host renders in a
sandboxed iframe. See https://modelcontextprotocol.io/specification/draft/extensions/apps
and SEP-2133 for the extension framework.

This is a self-contained, additive `Extension`: it contributes tools and
resources and advertises the capability, but does not intercept any core method.
A server opts in by passing an `Apps` instance to `MCPServer(extensions=[...])`.

    apps = Apps()

    @apps.tool(resource_uri="ui://clock/app.html", description="Current time")
    def get_time(ctx: Context) -> str:
        return datetime.now(timezone.utc).isoformat()

    apps.add_html_resource("ui://clock/app.html", CLOCK_HTML)

    mcp = MCPServer("clock", extensions=[apps])

Per SEP-2133, an extension MUST degrade gracefully: a UI-enabled tool should
still return meaningful text for clients that did not negotiate Apps. Use
`client_supports_apps(ctx)` to branch on the client's advertised support.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from mcp.server.context import ServerRequestContext
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.extension import Extension, ResourceBinding, ToolBinding
from mcp.server.mcpserver.resources import TextResource

EXTENSION_ID = "io.modelcontextprotocol/ui"
"""The MCP Apps extension identifier (the shipped TS/C# constant)."""

APP_MIME_TYPE = "text/html;profile=mcp-app"
"""MIME type for a `ui://` app resource."""

_CallableT = TypeVar("_CallableT", bound=Callable[..., Any])


class Apps(Extension):
    """The MCP Apps extension: bind tools to `ui://` UI resources.

    Register UI-bound tools with `@apps.tool(resource_uri=...)` and their HTML
    with `add_html_resource(...)`, then pass the instance to
    `MCPServer(extensions=[apps])`.
    """

    identifier = EXTENSION_ID

    def __init__(self) -> None:
        self._tools: list[ToolBinding] = []
        self._resources: list[ResourceBinding] = []

    def tool(self, *, resource_uri: str, **tool_kwargs: Any) -> Callable[[_CallableT], _CallableT]:
        """Decorator registering a tool bound to a `ui://` resource.

        Stamps `_meta.ui.resourceUri` on the tool. `tool_kwargs` are forwarded to
        `MCPServer.add_tool` (name, title, description, annotations, ...).

        Args:
            resource_uri: The `ui://` URI of the UI resource this tool renders.

        Raises:
            ValueError: If `resource_uri` does not use the `ui://` scheme.
        """
        _require_ui_scheme(resource_uri)

        def decorator(fn: _CallableT) -> _CallableT:
            meta = {"ui": {"resourceUri": resource_uri}}
            self._tools.append(ToolBinding(fn=fn, meta=meta, kwargs=tool_kwargs))
            return fn

        return decorator

    def add_html_resource(
        self,
        uri: str,
        html: str,
        *,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> None:
        """Register a `ui://` HTML resource served as `text/html;profile=mcp-app`.

        Args:
            uri: The `ui://` URI; a tool references it via `resource_uri`.
            html: The HTML document the host renders.

        Raises:
            ValueError: If `uri` does not use the `ui://` scheme.
        """
        _require_ui_scheme(uri)
        resource = TextResource(
            uri=uri,
            name=name or uri,
            title=title,
            description=description,
            mime_type=APP_MIME_TYPE,
            text=html,
        )
        self._resources.append(ResourceBinding(resource=resource))

    def tools(self) -> Sequence[ToolBinding]:
        return self._tools

    def resources(self) -> Sequence[ResourceBinding]:
        return self._resources


def client_supports_apps(ctx: Context[Any] | ServerRequestContext[Any, Any]) -> bool:
    """Whether the connected client negotiated MCP Apps support.

    Returns `False` when the client did not advertise the extension (or sent no
    capabilities), so a UI-enabled tool can fall back to text-only output.
    """
    capabilities = _client_capabilities(ctx)
    extensions = capabilities.extensions if capabilities else None
    return bool(extensions and EXTENSION_ID in extensions)


def _client_capabilities(ctx: Context[Any] | ServerRequestContext[Any, Any]) -> Any:
    if isinstance(ctx, Context):
        return ctx.client_capabilities
    client_params = ctx.session.client_params
    return client_params.capabilities if client_params else None


def _require_ui_scheme(uri: str) -> None:
    if not uri.startswith("ui://"):
        raise ValueError(f"MCP Apps URIs must use the ui:// scheme, got {uri!r}")
