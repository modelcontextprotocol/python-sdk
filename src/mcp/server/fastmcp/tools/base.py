from __future__ import annotations as _annotations

import inspect
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, get_origin

from pydantic import BaseModel, Field

from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata, func_metadata

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
    fn_metadata: FuncMetadata = Field(
        description="Metadata about the function including a pydantic model for tool"
        " arguments"
    )
    is_async: bool = Field(description="Whether the tool is async")
    context_kwarg: str | None = Field(
        None, description="Name of the kwarg that should receive context"
    )

    # Add a new class method for post-processing
    @classmethod
    def post_process_result(cls, result: Any, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Post-process the result of a tool execution.

        Override this method in a subclass to customize the post-processing behavior.

        Args:
            result: The result of the tool execution
            tool_name: The name of the tool that was executed
            arguments: The arguments that were passed to the tool

        Returns:
            The post-processed result
        """
        # Default implementation just returns the original result
        # You would replace this with your custom logic
        return result

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
        context_kwarg: str | None = None,
    ) -> Tool:
        """Create a Tool from a function."""
        from mcp.server.fastmcp import Context

        func_name = name or fn.__name__

        if func_name == "<lambda>":
            raise ValueError("You must provide a name for lambda functions")

        func_doc = description or fn.__doc__ or ""
        is_async = inspect.iscoroutinefunction(fn)

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
            result = await self.fn_metadata.call_fn_with_arg_validation(
                self.fn,
                self.is_async,
                arguments,
                {self.context_kwarg: context}
                if self.context_kwarg is not None
                else None,
            )
            # Post-process the result before returning
            return self.post_process_result(result, self.name, arguments)
        except Exception as e:
            raise ToolError(f"Error executing tool {self.name}: {e}") from e
