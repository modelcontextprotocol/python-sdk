from __future__ import annotations as _annotations

import functools
import inspect
import json
from collections.abc import Callable
from functools import cached_property
from typing import TYPE_CHECKING, Any, get_origin

from pydantic import Field

from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.resources import ToolResource
from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata, func_metadata
from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from mcp.server.fastmcp.server import Context
    from mcp.server.session import ServerSessionT
    from mcp.shared.context import LifespanContextT, RequestT


class Tool(ToolResource):
    """Internal tool registration info."""

    fn: Callable[..., Any] = Field(exclude=True)
    parameters: dict[str, Any] = Field(description="JSON schema for tool parameters")
    fn_metadata: FuncMetadata = Field(
        description="Metadata about the function including a pydantic model for tool arguments"
    )
    is_async: bool = Field(description="Whether the tool is async")
    context_kwarg: str | None = Field(None, description="Name of the kwarg that should receive context")
    annotations: ToolAnnotations | None = Field(None, description="Optional annotations for the tool")

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
        structured_output: bool | None = None,
    ) -> Tool:
        """Create a Tool from a function."""
        from mcp.server.fastmcp.server import Context

        func_name = name or fn.__name__

        if func_name == "<lambda>":
            raise ValueError("You must provide a name for lambda functions")

        func_doc = description or fn.__doc__ or ""
        is_async = _is_async_callable(fn)

        if context_kwarg is None:
            sig = inspect.signature(fn)
            for param_name, param in sig.parameters.items():
                if get_origin(param.annotation) is not None:
                    continue
                if issubclass(param.annotation, Context):
                    context_kwarg = param_name
                    break

        func_arg_metadata = func_metadata(
            fn,
            skip_names=[context_kwarg] if context_kwarg is not None else [],
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
            annotations=annotations,
        )

    async def read(self) -> str | bytes:
        """Read the tool schema/documentation as JSON."""
        tool_info = {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "uri": str(self.uri),
            "parameters": self.parameters,
        }

        # Include output schema if available
        if self.output_schema:
            tool_info["output_schema"] = self.output_schema

        # Include annotations if available
        if self.annotations:
            tool_info["annotations"] = self.annotations.model_dump(exclude_none=True)

        return json.dumps(tool_info, indent=2)

    async def run(
        self,
        arguments: dict[str, Any],
        context: Context[ServerSessionT, LifespanContextT, RequestT] | None = None,
        convert_result: bool = False,
    ) -> Any:
        """Run the tool with arguments."""
        try:
            result = await self.fn_metadata.call_fn_with_arg_validation(
                self.fn,
                self.is_async,
                arguments,
                {self.context_kwarg: context} if self.context_kwarg is not None else None,
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
