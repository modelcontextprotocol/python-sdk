"""Resource manager functionality."""

from collections.abc import Callable
from typing import Any

from pydantic import AnyUrl

from mcp.server.fastmcp.resources.base import Resource
from mcp.server.fastmcp.resources.templates import ResourceTemplate
from mcp.server.fastmcp.uri_utils import filter_by_uri_paths
from mcp.server.fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


class ResourceManager:
    """Manages FastMCP resources."""

    def __init__(self, warn_on_duplicate_resources: bool = True):
        self._resources: dict[str, Resource] = {}
        self._templates: dict[str, ResourceTemplate] = {}
        self.warn_on_duplicate_resources = warn_on_duplicate_resources

    def add_resource(self, resource: Resource) -> Resource:
        """Add a resource to the manager.

        Args:
            resource: A Resource instance to add

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
    ) -> ResourceTemplate:
        """Add a template from a function."""
        template = ResourceTemplate.from_function(
            fn,
            uri_template=uri_template,
            name=name,
            title=title,
            description=description,
            mime_type=mime_type,
        )
        self._templates[template.uri_template] = template
        return template

    async def get_resource(self, uri: AnyUrl | str) -> Resource | None:
        """Get resource by URI, checking concrete resources first, then templates."""
        uri_str = str(uri)
        logger.debug("Getting resource", extra={"uri": uri_str})

        # First check concrete resources
        if resource := self._resources.get(uri_str):
            return resource

        # Then check templates
        for template in self._templates.values():
            if params := template.matches(uri_str):
                try:
                    return await template.create_resource(uri_str, params)
                except Exception as e:
                    raise ValueError(f"Error creating resource from template: {e}")

        raise ValueError(f"Unknown resource: {uri}")

    def list_resources(self, uri_paths: list[str] | None = None) -> list[Resource]:
        """List all registered resources, optionally filtered by URI paths."""
        resources = list(self._resources.values())
        resources = filter_by_uri_paths(resources, uri_paths, lambda r: r.uri)
        logger.debug("Listing resources", extra={"count": len(resources), "uri_paths": uri_paths})
        return resources

    def list_templates(self, uri_paths: list[str] | None = None) -> list[ResourceTemplate]:
        """List all registered templates, optionally filtered by URI paths."""
        templates = list(self._templates.values())
        if uri_paths:
            filtered: list[ResourceTemplate] = []
            for template in templates:
                for prefix in uri_paths:
                    # Ensure prefix ends with / for proper path matching
                    if not prefix.endswith("/"):
                        prefix = prefix + "/"
                    if template.matches_prefix(prefix):
                        filtered.append(template)
                        break
            templates = filtered
        logger.debug("Listing templates", extra={"count": len(templates), "uri_paths": uri_paths})
        return templates
