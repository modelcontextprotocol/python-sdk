"""Resource template functionality."""

from __future__ import annotations

import inspect
import re
import urllib.parse
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, validate_call

from mcp.server.fastmcp.resources.types import FunctionResource, Resource
from mcp.server.fastmcp.utilities.context_injection import find_context_parameter, inject_context
from mcp.server.fastmcp.utilities.convertors import Convertor
from mcp.server.fastmcp.utilities.func_metadata import func_metadata, use_defaults_on_optional_validation_error
from mcp.server.fastmcp.utilities.param_validation import validate_and_sync_params
from mcp.types import Annotations, Icon

if TYPE_CHECKING:
    from mcp.server.fastmcp.server import Context
    from mcp.server.session import ServerSessionT
    from mcp.shared.context import LifespanContextT, RequestT


class ResourceTemplate(BaseModel):
    """A template for dynamically creating resources."""

    uri_template: str = Field(description="URI template with parameters (e.g. weather://{city}/current{?units,format})")
    name: str = Field(description="Name of the resource")
    title: str | None = Field(description="Human-readable title of the resource", default=None)
    description: str | None = Field(description="Description of what the resource does")
    mime_type: str = Field(default="text/plain", description="MIME type of the resource content")
    icons: list[Icon] | None = Field(default=None, description="Optional list of icons for the resource template")
    annotations: Annotations | None = Field(default=None, description="Optional annotations for the resource template")
    fn: Callable[..., Any] = Field(exclude=True)
    parameters: dict[str, Any] = Field(description="JSON schema for function parameters")
    context_kwarg: str | None = Field(None, description="Name of the kwarg that should receive context")
    compiled_pattern: re.Pattern[str] | None = Field(
        default=None, description="Compiled regular expression pattern for matching the URI template."
    )
    convertors: dict[str, Convertor[Any]] | None = Field(
        default=None, description="Mapping of parameter names to their respective type converters."
    )
    path_params: set[str] = Field(
        default_factory=set,
        description="Set of required parameters from the path component",
    )
    required_query_params: set[str] = Field(
        default_factory=set,
        description="Set of required parameters specified in the query component",
    )
    optional_query_params: set[str] = Field(
        default_factory=set,
        description="Set of optional parameters specified in the query component",
    )

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
        context_kwarg: str | None = None,
    ) -> ResourceTemplate:
        """Create a template from a function."""
        original_fn = fn
        func_name = name or original_fn.__name__
        if func_name == "<lambda>":
            raise ValueError("You must provide a name for lambda functions")  # pragma: no cover

        # Find context parameter if it exists
        if context_kwarg is None:  # pragma: no branch
            context_kwarg = find_context_parameter(fn)

        # Get schema from func_metadata, excluding context parameter
        func_arg_metadata = func_metadata(
            fn,
            skip_names=[context_kwarg] if context_kwarg is not None else [],
        )
        parameters = func_arg_metadata.arg_model.model_json_schema()

        # First, apply pydantic's validation and coercion
        validated_fn = validate_call(original_fn)

        # Then, apply our decorator to handle default fallback for optional params
        final_fn = use_defaults_on_optional_validation_error(validated_fn)

        # Extract required and optional params from the original function's signature
        (path_params, required_query_params, optional_query_params, convertors, compiled_pattern) = (
            validate_and_sync_params(original_fn, uri_template)
        )

        return cls(
            uri_template=uri_template,
            name=func_name,
            title=title,
            description=description or original_fn.__doc__ or "",
            mime_type=mime_type or "text/plain",
            icons=icons,
            annotations=annotations,
            fn=final_fn,
            parameters=parameters,
            context_kwarg=context_kwarg,
            path_params=path_params,
            required_query_params=required_query_params,
            optional_query_params=optional_query_params,
            convertors=convertors,
            compiled_pattern=compiled_pattern,
        )

    def matches(self, uri: str) -> dict[str, Any] | None:
        """Check if URI matches template and extract parameters."""
        if not self.compiled_pattern or not self.convertors:
            raise RuntimeError("Pattern did not compile for matching")

        # Split URI into path and query parts
        if "?" in uri:
            path, query = uri.split("?", 1)
        else:
            path, query = uri, ""

        match = self.compiled_pattern.match(path.strip("/"))
        if not match:
            return None

        params: dict[str, Any] = {}

        # ---- Extract and convert path parameters ----
        for name, conv in self.convertors.items():
            raw_value = match.group(name)
            try:
                params[name] = conv.convert(raw_value)
            except Exception as e:
                raise RuntimeError(f"Failed to convert '{raw_value}' for '{name}': {e}")

        # ---- Parse and merge query parameters ----
        query_dict = urllib.parse.parse_qs(query) if query else {}

        # Normalize and flatten query params
        for key, values in query_dict.items():
            value = values[0] if values else None
            if key in self.required_query_params or key in self.optional_query_params:
                params[key] = value

        # ---- Validate required query parameters ----
        missing_required = [key for key in self.required_query_params if key not in params]
        if missing_required:
            raise ValueError(f"Missing required query parameters: {missing_required}")

        return params

    async def create_resource(
        self,
        uri: str,
        params: dict[str, Any],
        context: Context[ServerSessionT, LifespanContextT, RequestT] | None = None,  # type: ignore
    ) -> Resource:
        """Create a resource from the template with the given parameters."""
        try:
            # Prepare parameters for function call
            # For optional parameters not in URL, use their default values
            # First add extracted parameters
            fn_params = {
                name: value
                for name, value in params.items()
                if name in self.path_params or name in self.required_query_params or name in self.optional_query_params
            }
            # Add context to params
            fn_params = inject_context(self.fn, fn_params, context, self.context_kwarg)  # type: ignore
            # self.fn is now multiply-decorated:
            # 1. validate_call for coercion/validation
            # 2. our new decorator for default fallback on optional param validation err
            result = self.fn(**fn_params)
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
                fn=lambda: result,  # Capture result in closure
            )
        except Exception as e:
            # This will catch errors from validate_call (e.g., for required params)
            # or from our decorator if retry also fails, or any other errors.
            raise ValueError(f"Error creating resource from template: {e}")
