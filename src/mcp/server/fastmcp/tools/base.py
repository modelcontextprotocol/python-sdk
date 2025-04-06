from __future__ import annotations as _annotations

import inspect
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, get_type_hints

from pydantic import BaseModel, Field

from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata, func_metadata

if TYPE_CHECKING:
    from mcp.server.fastmcp.server import Context
    from mcp.server.session import ServerSessionT
    from mcp.shared.context import LifespanContextT


def _is_context_type(annotation: type[Any]) -> bool:
    from mcp.server.fastmcp import Context

    if annotation is Context:
        return True
    if (
        generic_metadata := getattr(annotation, "__pydantic_generic_metadata__", None)
    ) is not None:
        return _is_context_type(generic_metadata["origin"])
    return False


class Tool(BaseModel):
    """Internal tool registration info."""

    fn: Callable[..., Any] = Field(exclude=True)
    name: str = Field(description="Name of the tool")
    description: str = Field(description="Description of what the tool does")
    parameters: dict[str, Any] = Field(description="JSON schema for tool parameters")
    fn_metadata: FuncMetadata = Field(
        description="Metadata about the function including a pydantic model for tool"
        " arguments"
    )
    is_async: bool = Field(description="Whether the tool is async")
    context_kwarg: str | None = Field(
        None, description="Name of the kwarg that should receive context"
    )

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
        context_kwarg: str | None = None,
    ) -> Tool:
        """Create a Tool from a function."""
        func_name = name or fn.__name__

        if func_name == "<lambda>":
            raise ValueError("You must provide a name for lambda functions")

        func_doc = description or fn.__doc__ or ""
        is_async = inspect.iscoroutinefunction(fn)

        if context_kwarg is None:
            type_hints = get_type_hints(fn)
            for param_name, param_type in type_hints.items():
                if param_name == "return":
                    continue
                if _is_context_type(param_type):
                    context_kwarg = param_name
                    break

        func_arg_metadata = func_metadata(
            fn,
            skip_names=[context_kwarg] if context_kwarg is not None else [],
        )
        parameters = func_arg_metadata.arg_model.model_json_schema()

        return cls(
            fn=fn,
            name=func_name,
            description=func_doc,
            parameters=parameters,
            fn_metadata=func_arg_metadata,
            is_async=is_async,
            context_kwarg=context_kwarg,
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
                {self.context_kwarg: context}
                if self.context_kwarg is not None
                else None,
            )
        except Exception as e:
            raise ToolError(f"Error executing tool {self.name}: {e}") from e
