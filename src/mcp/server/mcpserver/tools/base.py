from __future__ import annotations

from collections.abc import Callable, Hashable
from functools import cached_property
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.resolve import (
    build_resolver_plans,
    find_resolved_parameters,
    resolve_arguments,
)
from mcp.server.mcpserver.utilities.context_injection import find_context_parameter
from mcp.server.mcpserver.utilities.func_metadata import FuncMetadata, func_metadata
from mcp.shared._callable_inspection import is_async_callable
from mcp.shared.exceptions import MCPError
from mcp.shared.tool_name_validation import validate_and_warn_tool_name
from mcp.types import Icon, ToolAnnotations

if TYPE_CHECKING:
    from mcp.server.context import LifespanContextT, RequestT
    from mcp.server.mcpserver.context import Context


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
    resolved_params: dict[str, Any] = Field(
        default_factory=lambda: {},
        exclude=True,
        description="Parameters filled by resolvers, mapped to (Resolve, wants_union)",
    )
    resolver_plans: dict[Hashable, Any] = Field(
        default_factory=lambda: {}, exclude=True, description="Static per-resolver parameter plans"
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
        is_async = is_async_callable(fn)

        if context_kwarg is None:  # pragma: no branch
            context_kwarg = find_context_parameter(fn)

        resolved_params = find_resolved_parameters(fn)

        skip_names = [context_kwarg] if context_kwarg is not None else []
        skip_names.extend(resolved_params)

        func_arg_metadata = func_metadata(
            fn,
            skip_names=skip_names,
            structured_output=structured_output,
        )
        parameters = func_arg_metadata.arg_model.model_json_schema(by_alias=True)

        # Match `model_dump_one_level`'s kwarg keys (alias when present, else field name)
        # so a by-name resolver param resolves to a key that exists at call time.
        tool_arg_names = {field.alias or name for name, field in func_arg_metadata.arg_model.model_fields.items()}
        resolver_plans = build_resolver_plans(resolved_params, tool_arg_names)

        return cls(
            fn=fn,
            name=func_name,
            title=title,
            description=func_doc,
            parameters=parameters,
            fn_metadata=func_arg_metadata,
            is_async=is_async,
            context_kwarg=context_kwarg,
            resolved_params=dict(resolved_params),
            resolver_plans=resolver_plans,
            annotations=annotations,
            icons=icons,
            meta=meta,
        )

    async def run(
        self,
        arguments: dict[str, Any],
        context: Context[LifespanContextT, RequestT],
        convert_result: bool = False,
    ) -> Any:
        """Run the tool with arguments.

        Raises:
            ToolError: If the tool function raises during execution.
        """
        try:
            pass_directly: dict[str, Any] = {}
            if self.context_kwarg is not None:
                pass_directly[self.context_kwarg] = context

            # Resolvers see the same validated arguments the tool body receives:
            # validate once and reuse it, so a `default_factory`/stateful validator
            # can't hand a by-name resolver a different value than the body.
            pre_validated: dict[str, Any] | None = None
            if self.resolved_params:
                pre_validated = self.fn_metadata.validate_arguments(arguments)
                pass_directly |= await resolve_arguments(
                    self.resolved_params, self.resolver_plans, pre_validated, context
                )

            result = await self.fn_metadata.call_fn_with_arg_validation(
                self.fn,
                self.is_async,
                arguments,
                pass_directly or None,
                pre_validated=pre_validated,
            )

            if convert_result:
                result = self.fn_metadata.convert_result(result)

            return result
        except MCPError:
            # `MCPError` (and subclasses such as `UrlElicitationRequiredError`)
            # carries a JSON-RPC `ErrorData(code, message, data)` and means
            # "respond with a protocol error" - re-raise so the kernel surfaces
            # it as a top-level JSON-RPC error rather than wrapping it as a
            # `CallToolResult(isError=True)` execution failure.
            raise
        except Exception as e:
            raise ToolError(f"Error executing tool {self.name}: {e}") from e
