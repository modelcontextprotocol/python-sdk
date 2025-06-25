"""Resource template functionality."""

from __future__ import annotations

import inspect
import re
import urllib.parse
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, TypeAdapter, validate_call

from mcp.server.fastmcp.resources.types import FunctionResource, Resource
from mcp.server.fastmcp.utilities.func_metadata import (
    use_defaults_on_optional_validation_error,
)


class ResourceTemplate(BaseModel):
    """A template for dynamically creating resources."""

    uri_template: str = Field(description="URI template with parameters (e.g. weather://{city}/current{?units,format})")
    name: str = Field(description="Name of the resource")
    title: str | None = Field(description="Human-readable title of the resource", default=None)
    description: str | None = Field(description="Description of what the resource does")
    mime_type: str = Field(default="text/plain", description="MIME type of the resource content")
    fn: Callable[..., Any] = Field(exclude=True)
    parameters: dict[str, Any] = Field(description="JSON schema for function parameters")
    required_params: set[str] = Field(
        default_factory=set,
        description="Set of required parameters from the path component",
    )
    optional_params: set[str] = Field(
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
    ) -> ResourceTemplate:
        """Create a template from a function."""
        original_fn = fn
        func_name = name or original_fn.__name__
        if func_name == "<lambda>":
            raise ValueError("You must provide a name for lambda functions")

        # Get schema from TypeAdapter using the original function for correct schema
        parameters = TypeAdapter(original_fn).json_schema()

        # First, apply pydantic's validation and coercion
        validated_fn = validate_call(original_fn)

        # Then, apply our decorator to handle default fallback for optional params
        final_fn = use_defaults_on_optional_validation_error(validated_fn)

        # Extract required and optional params from the original function's signature
        required_params, optional_params = cls._analyze_function_params(original_fn)

        # Extract path parameters from URI template
        path_params: set[str] = set(re.findall(r"{(\w+)}", re.sub(r"{(\?.+?)}", "", uri_template)))

        # Extract query parameters from the URI template if present
        query_param_match = re.search(r"{(\?(?:\w+,)*\w+)}", uri_template)
        query_params: set[str] = set()
        if query_param_match:
            # Extract query parameters from {?param1,param2,...} syntax
            query_str = query_param_match.group(1)
            query_params = set(query_str[1:].split(","))  # Remove the leading '?' and split

        # Validate path parameters match required function parameters
        if path_params != required_params:
            raise ValueError(
                f"Mismatch between URI path parameters {path_params} "
                f"and required function parameters {required_params}"
            )

        # Validate query parameters are a subset of optional function parameters
        if not query_params.issubset(optional_params):
            invalid_params: set[str] = query_params - optional_params
            raise ValueError(
                f"Query parameters {invalid_params} do not match optional " f"function parameters {optional_params}"
            )

        return cls(
            uri_template=uri_template,
            name=func_name,
            title=title,
            description=description or original_fn.__doc__ or "",
            mime_type=mime_type or "text/plain",
            fn=final_fn,
            parameters=parameters,
            required_params=required_params,
            optional_params=optional_params,
        )

    @staticmethod
    def _analyze_function_params(fn: Callable[..., Any]) -> tuple[set[str], set[str]]:
        """Analyze function signature to extract required and optional parameters.
        This should operate on the original, unwrapped function.
        """
        # Ensure we are looking at the original function if it was wrapped elsewhere
        original_fn_for_analysis = inspect.unwrap(fn)
        required_params: set[str] = set()
        optional_params: set[str] = set()

        signature = inspect.signature(original_fn_for_analysis)
        for name, param in signature.parameters.items():
            # Parameters with default values are optional
            if param.default is param.empty:
                required_params.add(name)
            else:
                optional_params.add(name)

        return required_params, optional_params

    def matches(self, uri: str) -> dict[str, Any] | None:
        """Check if URI matches template and extract parameters."""
        # Split URI into path and query parts
        if "?" in uri:
            path, query = uri.split("?", 1)
        else:
            path, query = uri, ""

        # Remove the query parameter part from the template for matching
        path_template = re.sub(r"{(\?.+?)}", "", self.uri_template)

        # Convert template to regex pattern for path part
        pattern = path_template.replace("{", "(?P<").replace("}", ">[^/]+)")
        match = re.match(f"^{pattern}$", path)

        if not match:
            return None

        # Extract path parameters
        params = match.groupdict()

        # Parse and add query parameters if present
        if query:
            query_params = urllib.parse.parse_qs(query)
            for key, value in query_params.items():
                if key in self.optional_params:
                    # Use the first value if multiple are provided
                    params[key] = value[0] if value else None

        return params

    async def create_resource(self, uri: str, params: dict[str, Any]) -> Resource:
        """Create a resource from the template with the given parameters."""
        try:
            # Prepare parameters for function call
            # For optional parameters not in URL, use their default values

            # First add extracted parameters
            fn_params = {
                name: value
                for name, value in params.items()
                if name in self.required_params or name in self.optional_params
            }

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
                fn=lambda: result,  # Capture result in closure
            )
        except Exception as e:
            # This will catch errors from validate_call (e.g., for required params)
            # or from our decorator if retry also fails, or any other errors.
            raise ValueError(f"Error creating resource from template: {e}")
