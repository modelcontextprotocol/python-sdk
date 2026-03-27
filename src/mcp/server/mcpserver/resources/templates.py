"""Resource template functionality."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, validate_call

from mcp.server.mcpserver.resources.types import FunctionResource, Resource
from mcp.server.mcpserver.utilities.context_injection import find_context_parameter, inject_context
from mcp.server.mcpserver.utilities.func_metadata import func_metadata
from mcp.shared.path_security import contains_path_traversal, is_absolute_path
from mcp.shared.uri_template import UriTemplate
from mcp.types import Annotations, Icon

if TYPE_CHECKING:
    from mcp.server.context import LifespanContextT, RequestT
    from mcp.server.mcpserver.context import Context


@dataclass(frozen=True)
class ResourceSecurity:
    """Security policy applied to extracted resource template parameters.

    These checks run after :meth:`~mcp.shared.uri_template.UriTemplate.match`
    has extracted and decoded parameter values. They catch path-traversal
    and absolute-path injection regardless of how the value was encoded in
    the URI (literal, ``%2F``, ``%5C``, ``%2E%2E``).

    Example::

        # Opt out for a parameter that legitimately contains ..
        @mcp.resource(
            "git://diff/{+range}",
            security=ResourceSecurity(exempt_params={"range"}),
        )
        def git_diff(range: str) -> str: ...
    """

    reject_path_traversal: bool = True
    """Reject values containing ``..`` as a path component."""

    reject_absolute_paths: bool = True
    """Reject values that look like absolute filesystem paths."""

    reject_null_bytes: bool = True
    """Reject values containing NUL (``\\x00``). Null bytes defeat string
    comparisons (``"..\\x00" != ".."``) and can cause truncation in C
    extensions or subprocess calls."""

    exempt_params: Set[str] = field(default_factory=frozenset[str])
    """Parameter names to skip all checks for."""

    def validate(self, params: Mapping[str, str | list[str]]) -> bool:
        """Check all parameter values against the configured policy.

        Args:
            params: Extracted template parameters. List values (from
                explode variables) are checked element-wise.

        Returns:
            ``True`` if all values pass; ``False`` on first violation.
        """
        for name, value in params.items():
            if name in self.exempt_params:
                continue
            values = value if isinstance(value, list) else [value]
            for v in values:
                if self.reject_null_bytes and "\0" in v:
                    return False
                if self.reject_path_traversal and contains_path_traversal(v):
                    return False
                if self.reject_absolute_paths and is_absolute_path(v):
                    return False
        return True


DEFAULT_RESOURCE_SECURITY = ResourceSecurity()
"""Secure-by-default policy: traversal and absolute paths rejected."""


class ResourceTemplate(BaseModel):
    """A template for dynamically creating resources."""

    uri_template: str = Field(description="URI template with parameters (e.g. weather://{city}/current)")
    name: str = Field(description="Name of the resource")
    title: str | None = Field(description="Human-readable title of the resource", default=None)
    description: str | None = Field(description="Description of what the resource does")
    mime_type: str = Field(default="text/plain", description="MIME type of the resource content")
    icons: list[Icon] | None = Field(default=None, description="Optional list of icons for the resource template")
    annotations: Annotations | None = Field(default=None, description="Optional annotations for the resource template")
    meta: dict[str, Any] | None = Field(default=None, description="Optional metadata for this resource template")
    fn: Callable[..., Any] = Field(exclude=True)
    parameters: dict[str, Any] = Field(description="JSON schema for function parameters")
    context_kwarg: str | None = Field(None, description="Name of the kwarg that should receive context")
    parsed_template: UriTemplate = Field(exclude=True, description="Parsed RFC 6570 template")
    security: ResourceSecurity = Field(exclude=True, description="Path-safety policy for extracted parameters")

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., Any],
        uri_template: str,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
        icons: list[Icon] | None = None,
        annotations: Annotations | None = None,
        meta: dict[str, Any] | None = None,
        context_kwarg: str | None = None,
        security: ResourceSecurity = DEFAULT_RESOURCE_SECURITY,
    ) -> ResourceTemplate:
        """Create a template from a function.

        Raises:
            InvalidUriTemplate: If ``uri_template`` is malformed or uses
                unsupported RFC 6570 features.
        """
        func_name = name or fn.__name__
        if func_name == "<lambda>":
            raise ValueError("You must provide a name for lambda functions")  # pragma: no cover

        parsed = UriTemplate.parse(uri_template)

        # Find context parameter if it exists
        if context_kwarg is None:  # pragma: no branch
            context_kwarg = find_context_parameter(fn)

        # Get schema from func_metadata, excluding context parameter
        func_arg_metadata = func_metadata(
            fn,
            skip_names=[context_kwarg] if context_kwarg is not None else [],
        )
        parameters = func_arg_metadata.arg_model.model_json_schema()

        # ensure the arguments are properly cast
        fn = validate_call(fn)

        return cls(
            uri_template=uri_template,
            name=func_name,
            title=title,
            description=description or fn.__doc__ or "",
            mime_type=mime_type or "text/plain",
            icons=icons,
            annotations=annotations,
            meta=meta,
            fn=fn,
            parameters=parameters,
            context_kwarg=context_kwarg,
            parsed_template=parsed,
            security=security,
        )

    def matches(self, uri: str) -> dict[str, str | list[str]] | None:
        """Check if a URI matches this template and extract parameters.

        Delegates to :meth:`UriTemplate.match` for RFC 6570 extraction,
        then applies this template's :class:`ResourceSecurity` policy
        (path traversal, absolute paths).

        Returns:
            Extracted parameters on success, or ``None`` if the URI
            doesn't match or a parameter fails security validation.
        """
        params = self.parsed_template.match(uri)
        if params is None:
            return None
        if not self.security.validate(params):
            return None
        return params

    async def create_resource(
        self,
        uri: str,
        params: dict[str, Any],
        context: Context[LifespanContextT, RequestT],
    ) -> Resource:
        """Create a resource from the template with the given parameters.

        Raises:
            ValueError: If creating the resource fails.
        """
        try:
            # Add context to params if needed
            params = inject_context(self.fn, params, context, self.context_kwarg)

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
                icons=self.icons,
                annotations=self.annotations,
                meta=self.meta,
                fn=lambda: result,  # Capture result in closure
            )
        except Exception as e:
            raise ValueError(f"Error creating resource from template: {e}")
