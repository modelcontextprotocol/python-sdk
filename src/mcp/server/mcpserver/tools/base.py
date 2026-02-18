from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from functools import cached_property
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.utilities.context_injection import find_context_parameter
from mcp.server.mcpserver.utilities.dependencies import find_dependency_parameters
from mcp.server.mcpserver.utilities.func_metadata import FuncMetadata, func_metadata
from mcp.shared.exceptions import UrlElicitationRequiredError
from mcp.shared.tool_name_validation import validate_and_warn_tool_name
from mcp.types import Icon, ToolAnnotations

if TYPE_CHECKING:
    from mcp.server.context import LifespanContextT, RequestT
    from mcp.server.mcpserver.server import Context


class Tool(BaseModel):
    """Internal tool registration info."""

    fn: Callable[..., Any] = Field(exclude=True)
    name: str = Field(description="Name of the tool")
    title: str | None = Field(None, description="Human-readable title of the tool")
    description: str = Field(description="Description of what the tool does")
    parameters: dict[str, Any] = Field(description="JSON schema for tool parameters")
    fn_metadata: FuncMetadata = Field(
        description="Metadata about the function including a pydantic model for tool arguments"
    )
    is_async: bool = Field(description="Whether the tool is async")
    context_kwarg: str | None = Field(None, description="Name of the kwarg that should receive context")
    dependency_kwarg_names: list[str] = Field(
        default_factory=list,
        description="Names of kwargs that receive dependencies",
    )
    annotations: ToolAnnotations | None = Field(None, description="Optional annotations for the tool")
    icons: list[Icon] | None = Field(default=None, description="Optional list of icons for this tool")
    meta: dict[str, Any] | None = Field(default=None, description="Optional metadata for this tool")

    @cached_property
    def output_schema(self) -> dict[str, Any] | None:
        return self.fn_metadata.output_schema

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., Any],
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        context_kwarg: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        meta: dict[str, Any] | None = None,
        structured_output: bool | None = None,
    ) -> Tool:
        """Create a Tool from a function."""
        func_name = name or fn.__name__

        validate_and_warn_tool_name(func_name)

        if func_name == "<lambda>":
            raise ValueError("You must provide a name for lambda functions")

        func_doc = description or fn.__doc__ or ""
        is_async = _is_async_callable(fn)

        if context_kwarg is None:  # pragma: no branch
            context_kwarg = find_context_parameter(fn)

        # Find dependency parameters
        dependency_params = find_dependency_parameters(fn)
        dependency_kwarg_names = list(dependency_params.keys())

        # Skip both context and dependency params from arg_model
        skip_names = []
        if context_kwarg:
            skip_names.append(context_kwarg)
        skip_names.extend(dependency_kwarg_names)

        func_arg_metadata = func_metadata(
            fn,
            skip_names=skip_names,
            structured_output=structured_output,
        )
        parameters = func_arg_metadata.arg_model.model_json_schema(by_alias=True)

        return cls(
            fn=fn,
            name=func_name,
            title=title,
            description=func_doc,
            parameters=parameters,
            fn_metadata=func_arg_metadata,
            is_async=is_async,
            context_kwarg=context_kwarg,
            dependency_kwarg_names=dependency_kwarg_names,
            annotations=annotations,
            icons=icons,
            meta=meta,
        )

    async def run(
        self,
        arguments: dict[str, Any],
        context: Context[LifespanContextT, RequestT] | None = None,
        convert_result: bool = False,
        dependency_resolver: Any = None,
    ) -> Any:
        """Run the tool with arguments."""
        try:
            # Build direct args (context and dependencies)
            direct_args = {}
            if self.context_kwarg is not None and context is not None:
                direct_args[self.context_kwarg] = context

            # Resolve dependencies if a resolver is provided
            if self.dependency_kwarg_names and dependency_resolver:
                from mcp.server.mcpserver.utilities.dependencies import find_dependency_parameters

                deps = find_dependency_parameters(self.fn)
                for dep_name in self.dependency_kwarg_names:
                    if dep_name in deps:
                        direct_args[dep_name] = await dependency_resolver.resolve(dep_name, deps[dep_name])

            result = await self.fn_metadata.call_fn_with_arg_validation(
                self.fn,
                self.is_async,
                arguments,
                direct_args if direct_args else None,
            )

            if convert_result:
                result = self.fn_metadata.convert_result(result)

            return result
        except UrlElicitationRequiredError:
            # Re-raise UrlElicitationRequiredError so it can be properly handled
            # as an MCP error response with code -32042
            raise
        except Exception as e:
            raise ToolError(f"Error executing tool {self.name}: {e}") from e


def _is_async_callable(obj: Any) -> bool:
    while isinstance(obj, functools.partial):  # pragma: lax no cover
        obj = obj.func

    return inspect.iscoroutinefunction(obj) or (
        callable(obj) and inspect.iscoroutinefunction(getattr(obj, "__call__", None))
    )
