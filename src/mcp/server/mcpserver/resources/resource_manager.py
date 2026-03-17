"""Resource manager functionality."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pydantic import AnyUrl

from mcp.server.mcpserver.resources.base import Resource
from mcp.server.mcpserver.resources.templates import ResourceTemplate
from mcp.server.mcpserver.utilities.logging import get_logger
from mcp.types import Annotations, Icon

if TYPE_CHECKING:
    from mcp.server.context import LifespanContextT, RequestT
    from mcp.server.mcpserver.context import Context

logger = get_logger(__name__)


class ResourceManager:
    """Manages MCPServer resources with optional tenant-scoped storage.

    Resources and templates are stored in dicts keyed by
    ``(tenant_id, uri_string)`` and ``(tenant_id, uri_template)``
    respectively. This allows the same URI to exist independently under
    different tenants. When ``tenant_id`` is ``None`` (the default),
    entries live in a global scope, preserving backward compatibility
    with single-tenant usage.
    """

    def __init__(self, warn_on_duplicate_resources: bool = True):
        self._resources: dict[tuple[str | None, str], Resource] = {}
        self._templates: dict[tuple[str | None, str], ResourceTemplate] = {}
        self.warn_on_duplicate_resources = warn_on_duplicate_resources

    def add_resource(self, resource: Resource, *, tenant_id: str | None = None) -> Resource:
        """Add a resource to the manager, optionally scoped to a tenant.

        Args:
            resource: A Resource instance to add
            tenant_id: Optional tenant scope for the resource

        Returns:
            The added resource. If a resource with the same URI already exists,
            returns the existing resource.
        """
        logger.debug(
            "Adding resource",
            extra={
                "uri": resource.uri,
                "type": type(resource).__name__,
                "resource_name": resource.name,
            },
        )
        key = (tenant_id, str(resource.uri))
        existing = self._resources.get(key)
        if existing:
            if self.warn_on_duplicate_resources:
                logger.warning(f"Resource already exists: {resource.uri}")
            return existing
        self._resources[key] = resource
        return resource

    def add_template(
        self,
        fn: Callable[..., Any],
        uri_template: str,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
        icons: list[Icon] | None = None,
        annotations: Annotations | None = None,
        meta: dict[str, Any] | None = None,
        *,
        tenant_id: str | None = None,
    ) -> ResourceTemplate:
        """Add a template from a function, optionally scoped to a tenant."""
        template = ResourceTemplate.from_function(
            fn,
            uri_template=uri_template,
            name=name,
            title=title,
            description=description,
            mime_type=mime_type,
            icons=icons,
            annotations=annotations,
            meta=meta,
        )
        self._templates[(tenant_id, template.uri_template)] = template
        return template

    async def get_resource(
        self,
        uri: AnyUrl | str,
        context: Context[LifespanContextT, RequestT],
        *,
        tenant_id: str | None = None,
    ) -> Resource:
        """Get resource by URI, checking concrete resources first, then templates."""
        uri_str = str(uri)
        logger.debug("Getting resource", extra={"uri": uri_str})

        # First check concrete resources
        if resource := self._resources.get((tenant_id, uri_str)):
            return resource

        # Then check templates for this tenant scope
        for (tid, _), template in self._templates.items():
            if tid != tenant_id:
                continue
            if params := template.matches(uri_str):
                try:
                    return await template.create_resource(uri_str, params, context=context)
                except Exception as e:  # pragma: no cover
                    raise ValueError(f"Error creating resource from template: {e}")

        raise ValueError(f"Unknown resource: {uri}")

    def list_resources(self, *, tenant_id: str | None = None) -> list[Resource]:
        """List all registered resources for a given tenant scope."""
        resources = [r for (tid, _), r in self._resources.items() if tid == tenant_id]
        logger.debug("Listing resources", extra={"count": len(resources)})
        return resources

    def list_templates(self, *, tenant_id: str | None = None) -> list[ResourceTemplate]:
        """List all registered templates for a given tenant scope."""
        templates = [t for (tid, _), t in self._templates.items() if tid == tenant_id]
        logger.debug("Listing templates", extra={"count": len(templates)})
        return templates
