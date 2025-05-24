from __future__ import annotations as _annotations

import functools
import inspect
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, get_origin

from pydantic import BaseModel, Field

from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata, func_metadata
from mcp.server.fastmcp.utilities.schema import enhance_output_schema
from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from mcp.server.fastmcp.server import Context
    from mcp.server.session import ServerSessionT
    from mcp.shared.context import LifespanContextT


class Tool(BaseModel):
    """Internal tool registration info."""

    fn: Callable[..., Any] = Field(exclude=True)
    name: str = Field(description="Name of the tool")
    description: str = Field(description="Description of what the tool does")
    parameters: dict[str, Any] = Field(description="JSON schema for tool parameters")
    output_schema: dict[str, Any] | None = Field(
        None, description="JSON schema for tool output format"
    )
    fn_metadata: FuncMetadata = Field(
        description="Metadata about the function including a pydantic model for tool"
        " arguments"
    )
    is_async: bool = Field(description="Whether the tool is async")
    context_kwarg: str | None = Field(
        None, description="Name of the kwarg that should receive context"
    )
    annotations: ToolAnnotations | None = Field(
        None, description="Optional annotations for the tool"
    )

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
        context_kwarg: str | None = None,
        annotations: ToolAnnotations | None = None,
    ) -> Tool:
        """Create a Tool from a function."""
        from pydantic import TypeAdapter

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
        )
        parameters = func_arg_metadata.arg_model.model_json_schema()

        # Generate output schema from return type annotation if possible
        output_schema = None
        sig = inspect.signature(fn)
        if sig.return_annotation != inspect.Signature.empty:
            try:
                # Handle common return types that don't need schema
                if sig.return_annotation is str:
                    output_schema = {"type": "string"}
                elif sig.return_annotation is int:
                    output_schema = {"type": "integer"}
                elif sig.return_annotation is float:
                    output_schema = {"type": "number"}
                elif sig.return_annotation is bool:
                    output_schema = {"type": "boolean"}
                elif sig.return_annotation is dict:
                    output_schema = {"type": "object"}
                elif sig.return_annotation is list:
                    output_schema = {"type": "array"}
                else:
                    # Try to generate schema using TypeAdapter
                    return_type_adapter = TypeAdapter(sig.return_annotation)
                    output_schema = return_type_adapter.json_schema()

                # Enhance the schema with detailed field information
                if output_schema:
                    output_schema = enhance_output_schema(
                        output_schema, sig.return_annotation
                    )
            except Exception:
                # If we can't generate a schema, we'll leave it as None
                pass

        return cls(
            fn=fn,
            name=func_name,
            description=func_doc,
            parameters=parameters,
            fn_metadata=func_arg_metadata,
            is_async=is_async,
            context_kwarg=context_kwarg,
            annotations=annotations,
            output_schema=output_schema,
        )

    async def run(
        self,
        arguments: dict[str, Any],
        context: Context[ServerSessionT, LifespanContextT] | None = None,
    ) -> Any:
        """Run the tool with arguments."""
        try:
            return await self.fn_metadata.call_fn_with_arg_validation(
                self.fn,
                self.is_async,
                arguments,
                (
                    {self.context_kwarg: context}
                    if self.context_kwarg is not None
                    else None
                ),
            )
        except Exception as e:
            raise ToolError(f"Error executing tool {self.name}: {e}") from e


def _is_async_callable(obj: Any) -> bool:
    while isinstance(obj, functools.partial):
        obj = obj.func

    return inspect.iscoroutinefunction(obj) or (
        callable(obj) and inspect.iscoroutinefunction(getattr(obj, "__call__", None))
    )
