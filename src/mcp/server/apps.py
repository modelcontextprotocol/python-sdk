"""MCP Apps extension (`io.modelcontextprotocol/ui`).

A tool's `_meta.ui.resourceUri` points at a `ui://` resource (HTML served as
`text/html;profile=mcp-app`) that the host renders in a sandboxed iframe; a
server opts in via `MCPServer(extensions=[Apps()])`. Per SEP-2133 a UI-enabled
tool must degrade gracefully for clients that did not negotiate Apps — branch on
`client_supports_apps(ctx)`. Ships in-core (the TypeScript and C# SDKs package it
separately). Wire format:
https://modelcontextprotocol.io/specification/draft/extensions/apps
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
"""The MCP Apps extension identifier."""

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

    Register tools with `@apps.tool(resource_uri=...)`, their HTML with
    `add_html_resource(...)`, then pass the instance to `MCPServer(extensions=[apps])`.
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
        tool; `tool_kwargs` are forwarded to `MCPServer.add_tool` and `meta` keys
        merge alongside the `ui` entry.

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
        """Register a pre-built `ui://` resource (e.g. a `FileResource` serving HTML from disk).

        Without an explicit `mime_type` the resource is served as
        `text/html;profile=mcp-app`; hosts render `ui://` resources only under
        that MIME type, so an explicit mismatch is rejected.

        Raises:
            ValueError: If the URI does not use the `ui://` scheme, or an
                explicit `mime_type` is not `text/html;profile=mcp-app`.
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
            ValueError: If a tool's `resource_uri` has no resource registered on
                this instance — a `_meta.ui.resourceUri` that 404s on
                `resources/read` is a misconfiguration.
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

    True only when the client advertised the extension AND listed
    `text/html;profile=mcp-app` in its settings; UI-enabled tools should fall
    back to text-only output otherwise.
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
    client_params = ctx.session.client_params
    return client_params.capabilities if client_params else None


def _require_ui_scheme(uri: str) -> None:
    if not uri.startswith("ui://"):
        raise ValueError(f"MCP Apps URIs must use the ui:// scheme, got {uri!r}")
