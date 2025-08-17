"""Base classes for FastMCP prompts."""
from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal, TYPE_CHECKING

import pydantic_core
from pydantic import BaseModel, Field, TypeAdapter, validate_call

from mcp.types import ContentBlock, TextContent

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

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., PromptResult | Awaitable[PromptResult]],
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
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

        # detect context kwarg
        sig = inspect.signature(fn)
        context_kwarg: str | None = None
        for param_name, param in sig.parameters.items():
            ann = param.annotation
            if isinstance(ann, type) and issubclass(ann, Context):
                context_kwarg = param_name
                break

        # Get schema from TypeAdapter
        parameters = TypeAdapter(fn).json_schema()

        # Convert parameters to PromptArguments (skip context_kwarg if present)
        arguments: list[PromptArgument] = []
        if "properties" in parameters:
            for param_name, param in parameters["properties"].items():
                if param_name == context_kwarg:
                    continue
                required = param_name in parameters.get("required", [])
                arguments.append(
                    PromptArgument(
                        name=param_name,
                        description=param.get("description"),
                        required=required,
                    )
                )

        # ensure the arguments are properly cast
        fn = validate_call(fn)

        return cls(
            name=func_name,
            title=title,
            description=description or fn.__doc__ or "",
            arguments=arguments,
            fn=fn,
        )

    async def render(
            self, arguments: dict[str, Any] | None = None, 
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
            # Call function and check if result is a coroutine
            from mcp.server.state.helper.inject_ctx import inject_context 
            result = inject_context(self.fn, context, arguments) # This will be supported in FastMCP 2.0
            if inspect.iscoroutine(result):
                result = await result

            # Validate messages
            if not isinstance(result, list | tuple):
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
