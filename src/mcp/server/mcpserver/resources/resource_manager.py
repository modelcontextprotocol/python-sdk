"""Resource manager functionality."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mcp_types import Annotations, Icon, InputRequiredResult
from pydantic import AnyUrl

from mcp.server.mcpserver.exceptions import ResourceNotFoundError
from mcp.server.mcpserver.resources.base import Resource
from mcp.server.mcpserver.resources.templates import (
    DEFAULT_RESOURCE_SECURITY,
    ResourceSecurity,
    ResourceSecurityError,
    ResourceTemplate,
)
from mcp.server.mcpserver.utilities.logging import get_logger

if TYPE_CHECKING:
    from mcp.server.context import LifespanContextT, RequestT
    from mcp.server.mcpserver.context import Context

logger = get_logger(__name__)


class ResourceManager:
    """Manages MCPServer resources."""

    def __init__(self, warn_on_duplicate_resources: bool = True, *, resources: list[Resource] | None = None):
        self._resources: dict[str, Resource] = {}
        self._templates: dict[str, ResourceTemplate] = {}
        self.warn_on_duplicate_resources = warn_on_duplicate_resources

        for resource in resources or ():
            self.add_resource(resource)

    def add_resource(self, resource: Resource) -> Resource:
        """Add a resource to the manager.

        Args:
            resource: A Resource instance to add.

        Returns:
            The added resource. If a resource with the same URI already exists, returns the existing resource.
        """
        logger.debug(
            "Adding resource",
            extra={"uri": resource.uri, "type": type(resource).__name__, "resource_name": resource.name},
        )
        existing = self._resources.get(str(resource.uri))
        if existing:
            if self.warn_on_duplicate_resources:
                logger.warning(f"Resource already exists: {resource.uri}")
            return existing
        self._resources[str(resource.uri)] = resource
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
        security: ResourceSecurity = DEFAULT_RESOURCE_SECURITY,
    ) -> ResourceTemplate:
        """Add a template from a function."""
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
            security=security,
        )
        self._templates[template.uri_template] = template
        return template

    async def get_resource(
        self, uri: AnyUrl | str, context: Context[LifespanContextT, RequestT]
    ) -> Resource | InputRequiredResult:
        """Get resource by URI, checking concrete resources first, then templates.

        A template function may return an `InputRequiredResult` instead of
        resource content (the 2026-07-28 multi-round-trip flow); it is passed
        through unchanged.

        Raises:
            ResourceNotFoundError: If no resource or template matches the URI.
            ResourceError: If a matching template fails to create the resource.

        Note:
            Pydantic's ``AnyUrl`` normalises percent-encoding and
            resolves ``..`` segments during validation, so a value
            constructed as ``AnyUrl("file:///a/%2E%2E/b")`` arrives
            here as ``file:///b``. The JSON-RPC protocol layer passes
            raw ``str`` values and is unaffected, but internal callers
            wrapping URIs in ``AnyUrl`` should be aware that security
            checks see the already-normalised form.
        """
        uri_str = str(uri)
        logger.debug("Getting resource", extra={"uri": uri_str})

        # First check concrete resources
        if resource := self._resources.get(uri_str):
            return resource

        # Then check templates
        for template in self._templates.values():
            try:
                params = template.matches(uri_str)
            except ResourceSecurityError as e:
                raise ResourceNotFoundError(f"Unknown resource: {uri}") from e
            if params is not None:
                return await template.create_resource(uri_str, params, context=context)

        raise ResourceNotFoundError(f"Unknown resource: {uri}")

    def list_resources(self) -> list[Resource]:
        """List all registered resources."""
        logger.debug("Listing resources", extra={"count": len(self._resources)})
        return list(self._resources.values())

    def list_templates(self) -> list[ResourceTemplate]:
        """List all registered templates."""
        logger.debug("Listing templates", extra={"count": len(self._templates)})
        return list(self._templates.values())
