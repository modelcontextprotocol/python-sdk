"""Resource template functionality."""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, TypeAdapter, validate_call

from mcp.server.fastmcp.resources.types import FunctionResource, Resource


class ResourceTemplate(BaseModel):
    """A template for dynamically creating resources."""

    uri_template: str = Field(description="URI template with parameters (e.g. weather://{city}/current)")
    name: str = Field(description="Name of the resource")
    title: str | None = Field(description="Human-readable title of the resource", default=None)
    description: str | None = Field(description="Description of what the resource does")
    mime_type: str = Field(default="text/plain", description="MIME type of the resource content")
    fn: Callable[..., Any] = Field(exclude=True)
    parameters: dict[str, Any] = Field(description="JSON schema for function parameters")

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., Any],
        uri_template: str,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
    ) -> ResourceTemplate:
        """Create a template from a function."""
        func_name = name or fn.__name__
        if func_name == "<lambda>":
            raise ValueError("You must provide a name for lambda functions")

        # Get schema from TypeAdapter - will fail if function isn't properly typed
        parameters = TypeAdapter(fn).json_schema()

        # ensure the arguments are properly cast
        fn = validate_call(fn)

        return cls(
            uri_template=uri_template,
            name=func_name,
            title=title,
            description=description or fn.__doc__ or "",
            mime_type=mime_type or "text/plain",
            fn=fn,
            parameters=parameters,
        )

    def matches(self, uri: str) -> dict[str, Any] | None:
        """Check if URI matches template and extract parameters."""
        # Convert template to regex pattern
        pattern = self.uri_template.replace("{", "(?P<").replace("}", ">[^/]+)")
        match = re.match(f"^{pattern}$", uri)
        if match:
            return match.groupdict()
        return None

    def matches_prefix(self, prefix: str) -> bool:
        """Check if this template could match URIs with the given prefix."""

        # First, simple check: does the template itself start with the prefix?
        if self.uri_template.startswith(prefix):
            return True

        template_segments = self.uri_template.split("/")
        prefix_segments = prefix.split("/")

        # Handle trailing slash - it creates an empty last segment
        has_trailing_slash = prefix.endswith("/") and prefix_segments[-1] == ""
        if has_trailing_slash:
            # Remove the empty segment for comparison
            prefix_segments = prefix_segments[:-1]
            # Template must have more segments to generate something "under" this path
            if len(template_segments) <= len(prefix_segments):
                return False
        else:
            # Without trailing slash, prefix can't have more segments than template
            if len(prefix_segments) > len(template_segments):
                return False

        # Compare each segment
        for i, prefix_seg in enumerate(prefix_segments):
            template_seg = template_segments[i]

            # If template segment is a parameter, it can match any value
            if template_seg.startswith("{") and template_seg.endswith("}"):
                continue

            # If both are literals, they must match exactly
            if template_seg != prefix_seg:
                return False

        # All prefix segments matched
        return True

    async def create_resource(self, uri: str, params: dict[str, Any]) -> Resource:
        """Create a resource from the template with the given parameters."""
        try:
            # Call function and check if result is a coroutine
            result = self.fn(**params)
            if inspect.iscoroutine(result):
                result = await result

            return FunctionResource(
                uri=uri,  # type: ignore
                name=self.name,
                title=self.title,
                description=self.description,
                mime_type=self.mime_type,
                fn=lambda: result,  # Capture result in closure
            )
        except Exception as e:
            raise ValueError(f"Error creating resource from template: {e}")
