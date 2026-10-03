"""Base classes for MCPServer prompts."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Annotated, Any, Literal

import anyio.to_thread
import pydantic_core
from mcp_types import ContentBlock, Icon, InputRequiredResult, TextContent
from pydantic import BaseModel, Field, TypeAdapter, validate_call

from mcp.server.mcpserver.utilities.context_injection import find_context_parameter, inject_context
from mcp.server.mcpserver.utilities.func_metadata import func_metadata
from mcp.server.mcpserver.utilities.types import Audio, Image
from mcp.shared._callable_inspection import is_async_callable
from mcp.shared.exceptions import MCPError

if TYPE_CHECKING:
    from mcp.server.context import LifespanContextT, RequestT
    from mcp.server.mcpserver.context import Context


class Message(BaseModel):
    """Base class for all prompt messages.

    `content` may be a plain string (wrapped in `TextContent`), an `Image` or `Audio`
    helper (converted to `ImageContent` / `AudioContent`, reading the file for path-backed
    helpers), or any ready-made content block.

    Raises:
        OSError: If a path-backed `Image` or `Audio` cannot be read.
    """

    role: Literal["user", "assistant"]
    content: ContentBlock

    def __init__(self, content: str | ContentBlock | Image | Audio, **kwargs: Any):
        if isinstance(content, str):
            content = TextContent(type="text", text=content)
        elif isinstance(content, Image):
            content = content.to_image_content()
        elif isinstance(content, Audio):
            content = content.to_audio_content()
        super().__init__(content=content, **kwargs)


class UserMessage(Message):
    """A message from the user."""

    role: Literal["user", "assistant"] = "user"

    def __init__(self, content: str | ContentBlock | Image | Audio, **kwargs: Any):
        super().__init__(content=content, **kwargs)


class AssistantMessage(Message):
    """A message from the assistant."""

    role: Literal["user", "assistant"] = "assistant"

    def __init__(self, content: str | ContentBlock | Image | Audio, **kwargs: Any):
        super().__init__(content=content, **kwargs)


# Both classes accept either role, so the first arm always matches: validate left to right rather than
# trying both (which converted - and for path-backed Image/Audio, read - the content twice).
message_validator: TypeAdapter[UserMessage | AssistantMessage] = TypeAdapter(
    Annotated[UserMessage | AssistantMessage, Field(union_mode="left_to_right")]
)

_PromptResultItem = str | ContentBlock | Image | Audio | Message | dict[str, Any]
SyncPromptResult = _PromptResultItem | InputRequiredResult | Sequence[_PromptResultItem]
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
    icons: list[Icon] | None = Field(default=None, description="Optional list of icons for this prompt")
    context_kwarg: str | None = Field(None, description="Name of the kwarg that should receive context", exclude=True)

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., PromptResult | Awaitable[PromptResult]],
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        icons: list[Icon] | None = None,
        context_kwarg: str | None = None,
    ) -> Prompt:
        """Create a Prompt from a function.

        The function can return:
        - A string, content block, `Image` or `Audio` (each becomes a user message)
        - A Message object
        - A dict (converted to a message)
        - A sequence of any of the above
        - An InputRequiredResult (passed through unchanged; the 2026-07-28
          multi-round-trip flow — read `ctx.input_responses` on the retry)
        """
        func_name = name or fn.__name__

        if func_name == "<lambda>":  # pragma: no cover
            raise ValueError("You must provide a name for lambda functions")

        # Find context parameter if it exists
        if context_kwarg is None:  # pragma: no branch
            context_kwarg = find_context_parameter(fn)

        # Only the argument model is needed; a prompt has no output schema to derive
        func_arg_metadata = func_metadata(
            fn, skip_names=[context_kwarg] if context_kwarg is not None else [], structured_output=False
        )
        parameters = func_arg_metadata.arg_model.model_json_schema()

        # Convert parameters to PromptArguments
        arguments: list[PromptArgument] = []
        if "properties" in parameters:  # pragma: no branch
            for param_name, param in parameters["properties"].items():
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
            icons=icons,
            context_kwarg=context_kwarg,
        )

    async def render(
        self,
        arguments: dict[str, Any] | None,
        context: Context[LifespanContextT, RequestT],
    ) -> list[Message] | InputRequiredResult:
        """Render the prompt with arguments.

        An `InputRequiredResult` returned by the prompt function is passed
        through unchanged so the multi-round-trip flow reaches the client.

        Raises:
            ValueError: If required arguments are missing, or if rendering fails.
        """
        # Validate required arguments
        if self.arguments:
            required = {arg.name for arg in self.arguments if arg.required}
            provided = set(arguments or {})
            missing = required - provided
            if missing:
                raise ValueError(f"Missing required arguments: {missing}")

        try:
            # Add context to arguments if needed
            call_args = inject_context(self.fn, arguments or {}, context, self.context_kwarg)

            fn = self.fn
            if is_async_callable(fn):
                result = await fn(**call_args)
            else:
                result = await anyio.to_thread.run_sync(functools.partial(self.fn, **call_args))

            if isinstance(result, InputRequiredResult):
                return result

            # Validate messages
            if not isinstance(result, list | tuple):
                result = [result]

            # Convert result to messages
            messages: list[Message] = []
            for msg in result:  # type: ignore[reportUnknownVariableType]
                if isinstance(msg, Message):
                    messages.append(msg)
                elif isinstance(msg, dict):
                    messages.append(message_validator.validate_python(msg))
                elif isinstance(msg, str | ContentBlock | Image | Audio):  # bare content is one user message
                    messages.append(UserMessage(msg))
                else:  # pragma: no cover
                    content = pydantic_core.to_json(msg, fallback=str, indent=2).decode()
                    messages.append(Message(role="user", content=content))

            return messages
        except MCPError:
            raise
        except Exception as exc:
            raise ValueError(f"Error rendering prompt {self.name}") from exc
