"""Resource template functionality."""

from __future__ import annotations

import functools
from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import anyio.to_thread
from mcp_types import Annotations, Icon
from pydantic import BaseModel, Field, validate_call

from mcp.server.mcpserver.exceptions import ResourceError
from mcp.server.mcpserver.resources.types import FunctionResource, Resource
from mcp.server.mcpserver.utilities.context_injection import find_context_parameter, inject_context
from mcp.server.mcpserver.utilities.func_metadata import func_metadata
from mcp.server.mcpserver.utilities.logging import get_logger
from mcp.shared._callable_inspection import is_async_callable
from mcp.shared.path_security import contains_path_traversal, is_absolute_path
from mcp.shared.uri_template import UriTemplate

logger = get_logger(__name__)

if TYPE_CHECKING:
    from mcp.server.context import LifespanContextT, RequestT
    from mcp.server.mcpserver.context import Context


@dataclass(frozen=True)
class ResourceSecurity:
    """Security policy applied to extracted resource template parameters.

    Checks run after `UriTemplate.match` has decoded parameter values, so they catch
    traversal and absolute-path injection however the URI encoded them (`%2F`, `%5C`, `%2E%2E`).

    Example (opt out for a parameter that legitimately contains `..`):

        @mcp.resource("git://diff/{+range}", security=ResourceSecurity(exempt_params={"range"}))
        def git_diff(range: str) -> str: ...
    """

    reject_path_traversal: bool = True
    """Reject values containing `..` as a path component."""

    reject_absolute_paths: bool = True
    """Reject values that look like absolute filesystem paths."""

    reject_null_bytes: bool = True
    """Reject values containing NUL; null bytes defeat string comparisons and can
    cause truncation in C extensions or subprocess calls."""

    exempt_params: Set[str] = field(default_factory=frozenset[str])
    """Parameter names to skip all checks for."""

    def validate(self, params: Mapping[str, str | list[str]]) -> str | None:
        """Check parameter values against the policy; list values are checked element-wise.

        Returns:
            The name of the first failing parameter, or `None` if all values pass.
        """
        for name, value in params.items():
            if name in self.exempt_params:
                continue
            values = value if isinstance(value, list) else [value]
            for v in values:
                if self.reject_null_bytes and "\0" in v:
                    return name
                if self.reject_path_traversal and contains_path_traversal(v):
                    return name
                if self.reject_absolute_paths and is_absolute_path(v):
                    return name
        return None


DEFAULT_RESOURCE_SECURITY = ResourceSecurity()
"""Secure-by-default policy: traversal, absolute paths, and null bytes rejected."""


class ResourceSecurityError(ValueError):
    """Raised when an extracted parameter fails `ResourceSecurity` checks.

    Distinct from a `None` non-match so template iteration stops at the first
    security rejection instead of falling through to a more permissive template.
    """

    def __init__(self, template: str, param: str) -> None:
        super().__init__(f"Parameter {param!r} of template {template!r} failed security validation")
        self.template = template
        self.param = param


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
            InvalidUriTemplate: If `uri_template` is malformed or uses unsupported RFC 6570 features.
        """
        func_name = name or fn.__name__
        if func_name == "<lambda>":
            raise ValueError("You must provide a name for lambda functions")  # pragma: no cover

        parsed = UriTemplate.parse(uri_template)

        if context_kwarg is None:  # pragma: no branch
            context_kwarg = find_context_parameter(fn)

        func_arg_metadata = func_metadata(
            fn,
            skip_names=[context_kwarg] if context_kwarg is not None else [],
        )
        parameters = func_arg_metadata.arg_model.model_json_schema()

        # validate_call coerces arguments to their annotated types
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

        Returns:
            Extracted parameters, or `None` if the URI doesn't match.

        Raises:
            ResourceSecurityError: If a matched parameter fails security validation. Raising
                (not returning `None`) prevents the resource manager from silently falling
                through to a later, possibly more permissive, template.
        """
        params = self.parsed_template.match(uri)
        if params is None:
            return None
        failed = self.security.validate(params)
        if failed is not None:
            raise ResourceSecurityError(self.uri_template, failed)
        return params

    async def create_resource(
        self,
        uri: str,
        params: dict[str, Any],
        context: Context[LifespanContextT, RequestT],
    ) -> Resource:
        """Create a resource from the template with the given parameters.

        Raises:
            ResourceError: If creating the resource fails.
        """
        try:
            params = inject_context(self.fn, params, context, self.context_kwarg)

            fn = self.fn
            if is_async_callable(fn):
                result = await fn(**params)
            else:
                result = await anyio.to_thread.run_sync(functools.partial(self.fn, **params))

            return FunctionResource(
                uri=uri,  # type: ignore
                name=self.name,
                title=self.title,
                description=self.description,
                mime_type=self.mime_type,
                icons=self.icons,
                annotations=self.annotations,
                meta=self.meta,
                fn=lambda: result,
            )
        except ResourceError:
            raise
        except Exception as exc:
            logger.exception(f"Error creating resource from template {uri}")
            raise ResourceError(f"Error creating resource from template {uri}") from exc
