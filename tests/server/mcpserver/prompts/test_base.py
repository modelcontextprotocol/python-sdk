import threading
from pathlib import Path
from typing import Any

import pytest
from mcp_types import (
    AudioContent,
    ElicitRequest,
    ElicitRequestFormParams,
    EmbeddedResource,
    ImageContent,
    InputRequiredResult,
    TextContent,
    TextResourceContents,
)

from mcp.server.mcpserver import AssistantMessage, Audio, Context, Image, MCPServer, Message, UserMessage
from mcp.server.mcpserver.prompts.base import Prompt


class TestRenderPrompt:
    @pytest.mark.anyio
    async def test_basic_fn(self):
        def fn() -> str:
            return "Hello, world!"

        prompt = Prompt.from_function(fn)
        assert await prompt.render(None, Context()) == [
            UserMessage(content=TextContent(type="text", text="Hello, world!"))
        ]

    @pytest.mark.anyio
    async def test_async_fn(self):
        async def fn() -> str:
            return "Hello, world!"

        prompt = Prompt.from_function(fn)
        assert await prompt.render(None, Context()) == [
            UserMessage(content=TextContent(type="text", text="Hello, world!"))
        ]

    @pytest.mark.anyio
    async def test_fn_with_args(self):
        async def fn(name: str, age: int = 30) -> str:
            return f"Hello, {name}! You're {age} years old."

        prompt = Prompt.from_function(fn)
        assert await prompt.render({"name": "World"}, Context()) == [
            UserMessage(content=TextContent(type="text", text="Hello, World! You're 30 years old."))
        ]

    @pytest.mark.anyio
    async def test_fn_with_invalid_kwargs(self):
        async def fn(name: str, age: int = 30) -> str:  # pragma: no cover
            return f"Hello, {name}! You're {age} years old."

        prompt = Prompt.from_function(fn)
        with pytest.raises(ValueError):
            await prompt.render({"age": 40}, Context())

    @pytest.mark.anyio
    async def test_fn_returns_message(self):
        async def fn() -> UserMessage:
            return UserMessage(content="Hello, world!")

        prompt = Prompt.from_function(fn)
        assert await prompt.render(None, Context()) == [
            UserMessage(content=TextContent(type="text", text="Hello, world!"))
        ]

    @pytest.mark.anyio
    async def test_fn_returns_assistant_message(self):
        async def fn() -> AssistantMessage:
            return AssistantMessage(content=TextContent(type="text", text="Hello, world!"))

        prompt = Prompt.from_function(fn)
        assert await prompt.render(None, Context()) == [
            AssistantMessage(content=TextContent(type="text", text="Hello, world!"))
        ]

    @pytest.mark.anyio
    async def test_fn_returns_multiple_messages(self):
        expected: list[Message] = [
            UserMessage("Hello, world!"),
            AssistantMessage("How can I help you today?"),
            UserMessage("I'm looking for a restaurant in the center of town."),
        ]

        async def fn() -> list[Message]:
            return expected

        prompt = Prompt.from_function(fn)
        assert await prompt.render(None, Context()) == expected

    @pytest.mark.anyio
    async def test_fn_returns_list_of_strings(self):
        expected = [
            "Hello, world!",
            "I'm looking for a restaurant in the center of town.",
        ]

        async def fn() -> list[str]:
            return expected

        prompt = Prompt.from_function(fn)
        assert await prompt.render(None, Context()) == [UserMessage(t) for t in expected]

    @pytest.mark.anyio
    async def test_fn_returns_resource_content(self):
        """Test returning a message with resource content."""

        async def fn() -> UserMessage:
            return UserMessage(
                content=EmbeddedResource(
                    type="resource",
                    resource=TextResourceContents(
                        uri="file://file.txt",
                        text="File contents",
                        mime_type="text/plain",
                    ),
                )
            )

        prompt = Prompt.from_function(fn)
        assert await prompt.render(None, Context()) == [
            UserMessage(
                content=EmbeddedResource(
                    type="resource",
                    resource=TextResourceContents(
                        uri="file://file.txt",
                        text="File contents",
                        mime_type="text/plain",
                    ),
                )
            )
        ]

    @pytest.mark.anyio
    async def test_fn_returns_mixed_content(self):
        """Test returning messages with mixed content types."""

        async def fn() -> list[Message]:
            return [
                UserMessage(content="Please analyze this file:"),
                UserMessage(
                    content=EmbeddedResource(
                        type="resource",
                        resource=TextResourceContents(
                            uri="file://file.txt",
                            text="File contents",
                            mime_type="text/plain",
                        ),
                    )
                ),
                AssistantMessage(content="I'll help analyze that file."),
            ]

        prompt = Prompt.from_function(fn)
        assert await prompt.render(None, Context()) == [
            UserMessage(content=TextContent(type="text", text="Please analyze this file:")),
            UserMessage(
                content=EmbeddedResource(
                    type="resource",
                    resource=TextResourceContents(
                        uri="file://file.txt",
                        text="File contents",
                        mime_type="text/plain",
                    ),
                )
            ),
            AssistantMessage(content=TextContent(type="text", text="I'll help analyze that file.")),
        ]

    @pytest.mark.anyio
    async def test_fn_returns_dict_with_resource(self):
        """Test returning a dict with resource content."""

        async def fn() -> dict[str, Any]:
            return {
                "role": "user",
                "content": {
                    "type": "resource",
                    "resource": {
                        "uri": "file://file.txt",
                        "text": "File contents",
                        "mimeType": "text/plain",
                    },
                },
            }

        prompt = Prompt.from_function(fn)
        assert await prompt.render(None, Context()) == [
            UserMessage(
                content=EmbeddedResource(
                    type="resource",
                    resource=TextResourceContents(
                        uri="file://file.txt",
                        text="File contents",
                        mime_type="text/plain",
                    ),
                )
            )
        ]


@pytest.mark.anyio
async def test_sync_fn_runs_in_worker_thread():
    """Sync prompt functions must run in a worker thread, not the event loop."""

    main_thread = threading.get_ident()
    fn_thread: list[int] = []

    def blocking_fn() -> str:
        fn_thread.append(threading.get_ident())
        return "hello"

    prompt = Prompt.from_function(blocking_fn)
    messages = await prompt.render(None, Context())

    assert messages == [UserMessage(content=TextContent(type="text", text="hello"))]
    assert fn_thread[0] != main_thread


@pytest.mark.anyio
async def test_render_passes_input_required_result_through_unchanged():
    """Prompt.render returns the InputRequiredResult the function returned, bypassing
    message conversion entirely (SEP-2322 multi-round-trip pass-through)."""
    sentinel = InputRequiredResult(
        input_requests={
            "who": ElicitRequest(
                params=ElicitRequestFormParams(
                    message="Who is this for?",
                    requested_schema={
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                    },
                )
            )
        }
    )

    def asking_prompt() -> InputRequiredResult:
        return sentinel

    prompt = Prompt.from_function(asking_prompt)
    result = await prompt.render(None, Context())
    assert result is sentinel


@pytest.mark.parametrize(
    ("helper", "expected"),
    [
        (Image(data=b"img", format="png"), ImageContent(type="image", data="aW1n", mime_type="image/png")),
        (Audio(data=b"snd", format="wav"), AudioContent(type="audio", data="c25k", mime_type="audio/wav")),
    ],
)
def test_message_converts_image_and_audio_helpers_to_content_blocks(
    helper: Image | Audio, expected: ImageContent | AudioContent
) -> None:
    """SDK-defined: prompt messages accept the same `Image`/`Audio` helpers tools return."""
    assert UserMessage(helper).content == expected
    assert AssistantMessage(content=helper).content == expected


@pytest.mark.anyio
async def test_prompt_dict_result_accepts_image_helper_as_content() -> None:
    """SDK-defined: the dict form is validated through `Message.__init__`, so helpers convert there too."""

    def fn() -> dict[str, Any]:
        return {"role": "user", "content": Image(data=b"img", format="png")}

    assert await Prompt.from_function(fn).render(None, Context()) == [
        UserMessage(ImageContent(type="image", data="aW1n", mime_type="image/png"))
    ]


class _Slide:
    """A plain class pydantic cannot build a schema for."""


@pytest.mark.anyio
async def test_prompt_return_annotation_is_not_run_through_tool_output_schema_derivation() -> None:
    """SDK-defined: a prompt only needs its argument model, so an unschematizable return annotation
    registers (it used to raise from the tool structured-output machinery)."""
    mcp = MCPServer()

    @mcp.prompt()
    def deck(topic: str) -> list[_Slide]:
        raise NotImplementedError

    [listed] = await mcp.list_prompts()
    assert [arg.name for arg in listed.arguments or []] == ["topic"]


_PNG = Image(data=b"img", format="png")
_PNG_BLOCK = ImageContent(type="image", data="aW1n", mime_type="image/png")
_DOC = EmbeddedResource(
    type="resource", resource=TextResourceContents(uri="file://notes.md", text="notes", mime_type="text/markdown")
)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("returned", "expected"),
    [
        (_PNG, [UserMessage(_PNG_BLOCK)]),
        (_DOC, [UserMessage(_DOC)]),
        (["Look at this:", _PNG], [UserMessage("Look at this:"), UserMessage(_PNG_BLOCK)]),
    ],
)
async def test_bare_content_returned_from_a_prompt_becomes_user_messages(returned: Any, expected: list[Message]):
    """SDK-defined: what a tool may return bare (a content block, `Image`, `Audio`), a prompt may too;
    each item becomes one user message instead of being JSON-dumped into text."""

    def fn() -> Any:
        return returned

    assert await Prompt.from_function(fn).render(None, Context()) == expected


@pytest.mark.anyio
async def test_prompt_returning_media_with_an_unreadable_file_fails_to_render(tmp_path: Path) -> None:
    """SDK-defined: a bare `Image` whose file cannot be read fails the render (an error for the client)
    instead of degrading to a text message."""

    def fn() -> Image:
        return Image(path=tmp_path / "missing.png")

    with pytest.raises(ValueError):
        await Prompt.from_function(fn).render(None, Context())
