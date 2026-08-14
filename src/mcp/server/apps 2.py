"""MCP Apps extension (`io.modelcontextprotocol/ui`).

MCP Apps lets a tool carry a reference to an interactive UI: the tool's
`_meta.ui.resourceUri` points at a `ui://` resource (an HTML document served
with the `text/html;profile=mcp-app` MIME type) that the host renders in a
sandboxed iframe. See https://modelcontextprotocol.io/specification/draft/extensions/apps
and the ext-apps spec for the wire format, and SEP-2133 for the extension framework.

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
`client_supports_apps(ctx)` to branch on the client's advertised support. (The SDK
keeps Apps in-core under `mcp.server.apps` rather than a separate package; the
TypeScript and C# SDKs ship it as a standalone package.)
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from mcp.server.context import ServerRequestContext
from mcp.server.extension import Extension, ResourceBinding, ToolBinding
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.resources import Resource, TextResource

EXTENSION_ID = "io.modelcontextprotocol/ui"
"""The MCP Apps extension identifier (the shipped TS/C# constant)."""

APP_MIME_TYPE = "text/html;profile=mcp-app"
"""MIME type for a `ui://` app resource."""

Visibility = Literal["model", "app"]
"""Where a UI-bound tool is surfaced (`_meta.ui.visibility`)."""

_CallableT = TypeVar("_CallableT", bound=Callable[..., Any])


class ResourcePermissions(BaseModel):
    """Iframe permissions a `ui://` resource requests (`_meta.ui.permissions`)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    camera: dict[str, Any] | None = None
    microphone: dict[str, Any] | None = None
    geolocation: dict[str, Any] | None = None
    clipboard_write: dict[str, Any] | None = None


class ResourceCsp(BaseModel):
    """Content-Security-Policy domains for a `ui://` resource (`_meta.ui.csp`)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    connect_domains: list[str] | None = None
    resource_domains: list[str] | None = None
    frame_domains: list[str] | None = None
    base_uri_domains: list[str] | None = None


class Apps(Extension):
    """The MCP Apps extension: bind tools to `ui://` UI resources.

    Register UI-bound tools with `@apps.tool(resource_uri=...)` and their HTML
    with `add_html_resource(...)`, then pass the instance to
    `MCPServer(extensions=[apps])`.
    """

    identifier = EXTENSION_ID

    def __init__(self) -> None:
        self._tools: list[tuple[ToolBinding, str]] = []  # (binding, bound resource_uri)
        self._resources: list[ResourceBinding] = []

    def tool(
        self,
        *,
        resource_uri: str,
        visibility: Sequence[Visibility] | None = None,
        meta: dict[str, Any] | None = None,
        **tool_kwargs: Any,
    ) -> Callable[[_CallableT], _CallableT]:
        """Decorator registering a tool bound to a `ui://` resource.

        Stamps `_meta.ui.resourceUri` (and `_meta.ui.visibility` when given) on the
        tool. `tool_kwargs` are forwarded to `MCPServer.add_tool` (name, title,
        description, annotations, ...); pass `meta=` to merge extra `_meta` keys
        alongside the `ui` entry.

        Args:
            resource_uri: The `ui://` URI of the UI resource this tool renders.
            visibility: Where the tool is surfaced (`["model", "app"]`).
            meta: Additional `_meta` keys to merge with the `ui` entry.

        Raises:
            ValueError: If `resource_uri` does not use the `ui://` scheme, or
                `meta` carries a `"ui"` key (the decorator owns `_meta["ui"]`).
        """
        _require_ui_scheme(resource_uri)
        if meta and "ui" in meta:
            raise ValueError("Apps.tool() owns _meta['ui']; pass resource_uri=/visibility= instead of a 'ui' meta key")
        ui: dict[str, Any] = {"resourceUri": resource_uri}
        if visibility is not None:
            ui["visibility"] = list(visibility)

        def decorator(fn: _CallableT) -> _CallableT:
            binding = ToolBinding(fn=fn, meta={**(meta or {}), "ui": ui}, kwargs=tool_kwargs)
            self._tools.append((binding, resource_uri))
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
        csp: ResourceCsp | None = None,
        permissions: ResourcePermissions | None = None,
        domain: str | None = None,
        prefers_border: bool | None = None,
    ) -> None:
        """Register a `ui://` HTML resource served as `text/html;profile=mcp-app`.

        `csp`, `permissions`, `domain`, and `prefers_border` populate the
        resource's `_meta.ui` per the ext-apps spec.

        Args:
            uri: The `ui://` URI; a tool references it via `resource_uri`.
            html: The HTML document the host renders.

        Raises:
            ValueError: If `uri` does not use the `ui://` scheme.
        """
        ui: dict[str, Any] = {}
        if csp is not None:
            ui["csp"] = csp.model_dump(by_alias=True, exclude_none=True)
        if permissions is not None:
            ui["permissions"] = permissions.model_dump(by_alias=True, exclude_none=True)
        if domain is not None:
            ui["domain"] = domain
        if prefers_border is not None:
            ui["prefersBorder"] = prefers_border
        self.add_resource(
            TextResource(
                uri=uri,
                name=name or uri,
                title=title,
                description=description,
                mime_type=APP_MIME_TYPE,
                meta={"ui": ui} if ui else None,
                text=html,
            )
        )

    def add_resource(self, resource: Resource) -> None:
        """Register a pre-built `ui://` resource.

        The escape hatch for resources `add_html_resource` cannot express (e.g. a
        `FileResource` serving HTML from disk). A resource without an explicit
        `mime_type` is served as `text/html;profile=mcp-app` — hosts will not
        render a `ui://` resource under any other MIME type, so an explicit
        mismatch is rejected.

        Raises:
            ValueError: If the resource URI does not use the `ui://` scheme, or
                its explicit `mime_type` is not `text/html;profile=mcp-app`.
        """
        _require_ui_scheme(resource.uri)
        if "mime_type" not in resource.model_fields_set:
            resource = resource.model_copy(update={"mime_type": APP_MIME_TYPE})
        elif resource.mime_type != APP_MIME_TYPE:
            raise ValueError(f"MCP Apps resources are served as {APP_MIME_TYPE!r}, got {resource.mime_type!r}")
        self._resources.append(ResourceBinding(resource=resource))

    def tools(self) -> Sequence[ToolBinding]:
        """The bound tools.

        Raises:
            ValueError: If a tool's `resource_uri` has no matching resource
                registered on this instance — a tool advertising a
                `_meta.ui.resourceUri` that 404s on `resources/read` is a
                misconfiguration, caught when the server consumes the extension.
        """
        registered = {binding.resource.uri for binding in self._resources}
        for tool, uri in self._tools:
            if uri not in registered:
                raise ValueError(
                    f"Apps tool {tool.fn.__name__!r} binds resource_uri {uri!r}, but no such resource "
                    "is registered; add it with add_html_resource() or add_resource()"
                )
        return [tool for tool, _ in self._tools]

    def resources(self) -> Sequence[ResourceBinding]:
        return self._resources


def client_supports_apps(ctx: Context[Any] | ServerRequestContext[Any, Any]) -> bool:
    """Whether the connected client negotiated MCP Apps support.

    Returns `True` only when the client advertised the extension AND listed the
    `text/html;profile=mcp-app` MIME type in its settings, so a UI-enabled tool
    can fall back to text-only output otherwise.
    """
    capabilities = _client_capabilities(ctx)
    extensions = capabilities.extensions if capabilities else None
    settings = extensions.get(EXTENSION_ID) if extensions else None
    if settings is None:
        return False
    mime_types = settings.get("mimeTypes")
    return isinstance(mime_types, list | tuple) and APP_MIME_TYPE in mime_types


def _client_capabilities(ctx: Context[Any] | ServerRequestContext[Any, Any]) -> Any:
    if isinstance(ctx, Context):
        return ctx.client_capabilities
    return ctx.session.client_capabilities


def _require_ui_scheme(uri: str) -> None:
    if not uri.startswith("ui://"):
        raise ValueError(f"MCP Apps URIs must use the ui:// scheme, got {uri!r}")
