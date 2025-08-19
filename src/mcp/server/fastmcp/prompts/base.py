"""Base classes for FastMCP prompts."""
from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal, TYPE_CHECKING, get_origin
from functools import cached_property

import pydantic_core
from pydantic import BaseModel, Field, TypeAdapter

from mcp.types import ContentBlock, TextContent
from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata, func_metadata

if TYPE_CHECKING:
    from mcp.server.fastmcp.server import Context
    from mcp.server.session import ServerSessionT
    from mcp.shared.context import LifespanContextT, RequestT


class Message(BaseModel):
    """Base class for all prompt messages."""

    role: Literal["user", "assistant"]
    content: ContentBlock

    def __init__(self, content: str | ContentBlock, **kwargs: Any):
        if isinstance(content, str):
            content = TextContent(type="text", text=content)
        super().__init__(content=content, **kwargs)


class UserMessage(Message):
    """A message from the user."""

    role: Literal["user", "assistant"] = "user"

    def __init__(self, content: str | ContentBlock, **kwargs: Any):
        super().__init__(content=content, **kwargs)


class AssistantMessage(Message):
    """A message from the assistant."""

    role: Literal["user", "assistant"] = "assistant"

    def __init__(self, content: str | ContentBlock, **kwargs: Any):
        super().__init__(content=content, **kwargs)


message_validator = TypeAdapter[UserMessage | AssistantMessage](UserMessage | AssistantMessage)

SyncPromptResult = str | Message | dict[str, Any] | Sequence[str | Message | dict[str, Any]]
PromptResult = SyncPromptResult | Awaitable[SyncPromptResult]


class PromptArgument(BaseModel):
    """An argument that can be passed to a prompt."""

    name: str = Field(description="Name of the argument")
    description: str | None = Field(None, description="Description of what the argument does")
    required: bool = Field(default=False, description="Whether the argument is required")


class Prompt(BaseModel):
    """A prompt template that can be rendered with parameters."""

    name: str = Field(description="Name of the prompt")
    title: str | None = Field(None, description="Human-readable title of the prompt")
    description: str | None = Field(None, description="Description of what the prompt does")
    arguments: list[PromptArgument] | None = Field(None, description="Arguments that can be passed to the prompt")
    fn: Callable[..., PromptResult | Awaitable[PromptResult]] = Field(exclude=True)
    fn_metadata: FuncMetadata = Field(
        description="Metadata about the function including a pydantic model for prompt arguments"
    )
    is_async: bool = Field(description="Whether the prompt function is async")
    context_kwarg: str | None = Field(None, description="Name of the kwarg that should receive context")

    @cached_property
    def output_schema(self) -> dict[str, Any] | None:
        return self.fn_metadata.output_schema

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., PromptResult | Awaitable[PromptResult]],
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        context_kwarg: str | None = None,
    ) -> "Prompt":
        """Create a Prompt from a function.

        The function can return:
        - A string (converted to a message)
        - A Message object
        - A dict (converted to a message)
        - A sequence of any of the above
        """
        from mcp.server.fastmcp.server import Context  # local import to avoid cycles

        func_name = name or fn.__name__
        if func_name == "<lambda>":
            raise ValueError("You must provide a name for lambda functions")

        func_doc = description or fn.__doc__ or ""
        is_async = _is_async_callable(fn)

        # Auto-detect context kwarg if not provided
        if context_kwarg is None:
            sig = inspect.signature(fn)
            for param_name, param in sig.parameters.items():
                if get_origin(param.annotation) is not None:
                    continue
                try:
                    if isinstance(param.annotation, type) and issubclass(param.annotation, Context):
                        context_kwarg = param_name
                        break
                except TypeError:
                    # Handle cases where param.annotation is not a class
                    continue

        # Get function metadata (excluding context kwarg from parameters)
        func_arg_metadata = func_metadata(
            fn,
            skip_names=[context_kwarg] if context_kwarg is not None else [],
        )

        # Get parameters schema for arguments (context kwarg excluded)
        parameters = func_arg_metadata.arg_model.model_json_schema(by_alias=True)

        # Convert parameters to PromptArguments
        arguments: list[PromptArgument] = []
        if "properties" in parameters:
            for param_name, param in parameters["properties"].items():
                required = param_name in parameters.get("required", [])
                arguments.append(
                    PromptArgument(
                        name=param_name,
                        description=param.get("description"),
                        required=required,
                    )
                )

        return cls(
            name=func_name,
            title=title,
            description=func_doc,
            arguments=arguments,
            fn=fn,
            fn_metadata=func_arg_metadata,
            is_async=is_async,
            context_kwarg=context_kwarg,
        )

    async def render(
        self, 
        arguments: dict[str, Any] | None = None, 
        context: Context[ServerSessionT, LifespanContextT, RequestT] | None = None,
    ) -> list[Message]:
        """Render the prompt with arguments."""
        # Validate required arguments
        if self.arguments:
            required = {arg.name for arg in self.arguments if arg.required}
            provided = set(arguments or {})
            missing = required - provided
            if missing:
                raise ValueError(f"Missing required arguments: {missing}")

        try:
            # Use the same pattern as Tool.run()
            result = await self.fn_metadata.call_fn_with_arg_validation(
                self.fn,
                self.is_async,
                arguments or {},
                {self.context_kwarg: context} if self.context_kwarg is not None else None,
            )

            # Validate messages
            if not isinstance(result, (list, tuple)):
                result = [result]

            # Convert result to messages
            messages: list[Message] = []
            for msg in result:  # type: ignore[reportUnknownVariableType]
                try:
                    if isinstance(msg, Message):
                        messages.append(msg)
                    elif isinstance(msg, dict):
                        messages.append(message_validator.validate_python(msg))
                    elif isinstance(msg, str):
                        content = TextContent(type="text", text=msg)
                        messages.append(UserMessage(content=content))
                    else:
                        content = pydantic_core.to_json(msg, fallback=str, indent=2).decode()
                        messages.append(Message(role="user", content=content))
                except Exception:
                    raise ValueError(f"Could not convert prompt result to message: {msg}")

            return messages
        except Exception as e:
            raise ValueError(f"Error rendering prompt {self.name}: {e}")


def _is_async_callable(obj: Any) -> bool:
    """Check if an object is an async callable (copied from Tool implementation)."""
    while isinstance(obj, functools.partial):
        obj = obj.func

    return inspect.iscoroutinefunction(obj) or (
        callable(obj) and inspect.iscoroutinefunction(getattr(obj, "__call__", None))
    )