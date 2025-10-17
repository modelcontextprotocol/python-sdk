from __future__ import annotations as _annotations

import functools
import inspect
from collections.abc import Callable
from functools import cached_property
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.utilities.context_injection import find_context_parameter
from mcp.server.fastmcp.utilities.dependencies import DependencyResolver, find_dependencies
from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata, func_metadata
from mcp.types import Depends, Icon, ToolAnnotations

if TYPE_CHECKING:
    from mcp.server.fastmcp.server import Context
    from mcp.server.session import ServerSessionT
    from mcp.shared.context import LifespanContextT, RequestT


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
    dependencies: dict[str, Depends] | None = Field(None, description="Tool dependencies")
    annotations: ToolAnnotations | None = Field(None, description="Optional annotations for the tool")
    icons: list[Icon] | None = Field(default=None, description="Optional list of icons for this tool")

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
        dependencies: dict[str, Depends] | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        structured_output: bool | None = None,
    ) -> Tool:
        """Create a Tool from a function."""
        func_name = name or fn.__name__

        if func_name == "<lambda>":
            raise ValueError("You must provide a name for lambda functions")

        func_doc = description or fn.__doc__ or ""
        is_async = _is_async_callable(fn)

        if context_kwarg is None:
            context_kwarg = find_context_parameter(fn)

        if dependencies is None:
            dependencies = find_dependencies(fn)

        skip_names = [context_kwarg] if context_kwarg is not None else []
        if dependencies:
            skip_names.extend(dependencies.keys())

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
            dependencies=dependencies,
            annotations=annotations,
            icons=icons,
        )

    async def run(
        self,
        arguments: dict[str, Any],
        context: Context[ServerSessionT, LifespanContextT, RequestT] | None = None,
        convert_result: bool = False,
    ) -> Any:
        """Run the tool with arguments."""
        dependency_resolver = DependencyResolver()
        try:
            # Resolve dependencies
            resolved_dependencies = await dependency_resolver.resolve_dependencies(self.dependencies or {})

            # Prepare arguments to pass directly to the function
            arguments_to_pass_directly = {self.context_kwarg: context} if self.context_kwarg is not None else {}
            arguments_to_pass_directly.update(resolved_dependencies)

            result = await self.fn_metadata.call_fn_with_arg_validation(
                self.fn,
                self.is_async,
                arguments,
                arguments_to_pass_directly,
            )

            if convert_result:
                result = self.fn_metadata.convert_result(result)

            return result
        except Exception as e:
            raise ToolError(f"Error executing tool {self.name}: {e}") from e


def _is_async_callable(obj: Any) -> bool:
    while isinstance(obj, functools.partial):
        obj = obj.func

    return inspect.iscoroutinefunction(obj) or (
        callable(obj) and inspect.iscoroutinefunction(getattr(obj, "__call__", None))
    )
