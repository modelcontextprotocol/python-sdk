from __future__ import annotations as _annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from functools import cached_property
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.utilities.context_injection import find_context_parameter
from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata, func_metadata
from mcp.types import ContentBlock, Icon, ToolAnnotations

if TYPE_CHECKING:
    from mcp.server.fastmcp.server import Context
    from mcp.server.session import ServerSessionT
    from mcp.shared.context import LifespanContextT, RequestT

InvocationMode = Literal["sync", "async"]


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
    annotations: ToolAnnotations | None = Field(None, description="Optional annotations for the tool")
    icons: list[Icon] | None = Field(default=None, description="Optional list of icons for this tool")
    invocation_modes: list[InvocationMode] = Field(
        default=["sync"], description="Supported invocation modes (sync/async)"
    )
    immediate_result: Callable[..., Awaitable[list[ContentBlock]]] | None = Field(
        None, exclude=True, description="Optional immediate result function for async tools"
    )
    meta: dict[str, Any] | None = Field(description="Optional additional tool information.", default=None)

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
        structured_output: bool | None = None,
        invocation_modes: list[InvocationMode] | None = None,
        keep_alive: int | None = None,
        immediate_result: Callable[..., Awaitable[list[Any]]] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Tool:
        """Create a Tool from a function."""
        func_name = name or fn.__name__

        if func_name == "<lambda>":
            raise ValueError("You must provide a name for lambda functions")

        func_doc = description or fn.__doc__ or ""
        is_async = _is_async_callable(fn)

        if context_kwarg is None:
            context_kwarg = find_context_parameter(fn)

        func_arg_metadata = func_metadata(
            fn,
            skip_names=[context_kwarg] if context_kwarg is not None else [],
            structured_output=structured_output,
        )
        parameters = func_arg_metadata.arg_model.model_json_schema(by_alias=True)

        # Default to sync mode if no invocation modes specified
        if invocation_modes is None:
            invocation_modes = ["sync"]

        # Set appropriate default keep_alive based on async compatibility
        # if user didn't specify custom keep_alive
        if keep_alive is None and "async" in invocation_modes:
            keep_alive = 3600  # Default for async-compatible tools

        # Validate keep_alive is only used with async-compatible tools
        if keep_alive is not None and "async" not in invocation_modes:
            raise ValueError(
                f"keep_alive parameter can only be used with async-compatible tools. "
                f"Tool '{func_name}' has invocation_modes={invocation_modes} "
                f"but specifies keep_alive={keep_alive}. "
                f"Add 'async' to invocation_modes to use keep_alive."
            )

        # Process meta dictionary and add keep_alive if specified
        meta = meta or {}
        if keep_alive is not None:
            meta = meta.copy()  # Don't modify the original dict
            meta["_keep_alive"] = keep_alive

        # Validate immediate_result usage
        if immediate_result is not None:
            # Check if tool supports async invocation
            if "async" not in invocation_modes:
                raise ValueError(
                    "immediate_result can only be used with async-compatible tools. "
                    "Add 'async' to invocation_modes to use immediate_result."
                )

            # Validate that immediate_result is an async callable
            if not _is_async_callable(immediate_result):
                raise ValueError("immediate_result must be an async callable that returns list[ContentBlock]")

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
            icons=icons,
            invocation_modes=invocation_modes,
            immediate_result=immediate_result,
            meta=meta,
        )

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
