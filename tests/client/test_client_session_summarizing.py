from typing import Any

import anyio
import pytest

from mcp.client.client_session_summarizing import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_SUMMARIZE_THRESHOLD,
    DEFAULT_SUMMARY_PROMPT,
    ClientSessionSummarizing,
)
from mcp.shared.context import RequestContext
from mcp.types import (
    CreateMessageRequestParams,
    CreateMessageResult,
    SamplingMessage,
    TextContent,
)


@pytest.mark.asyncio
async def test_summarizing_session():
    send_stream, receive_stream = anyio.create_memory_object_stream(10)
    try:
        session = ClientSessionSummarizing(
            read_stream=receive_stream,
            write_stream=send_stream,
        )

        # Create real messages instead of simple strings
        messages = [SamplingMessage(role="user", content=TextContent(type="text", text="Hello")) for _ in range(3500)]
        session.history = messages  # Simulate approaching token limit

        assert session.token_count() > session.max_tokens * session.summarize_threshold

        # Test that summarization works
        await session.summarize_context()

        # After summarization, history should contain only one message
        assert len(session.history) == 1
        assert isinstance(session.history[0], SamplingMessage)
        assert session.history[0].role == "assistant"

    finally:
        await send_stream.aclose()
        await receive_stream.aclose()


@pytest.mark.asyncio
async def test_sampling_callback():
    """Test sampling callback with ClientSessionSummarizing"""
    send_stream, receive_stream = anyio.create_memory_object_stream(10)
    try:
        session = ClientSessionSummarizing(
            read_stream=receive_stream,
            write_stream=send_stream,
        )

        # Create request parameters
        params = CreateMessageRequestParams(
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text="Hello world"))], maxTokens=100
        )

        # Create simple context for testing
        context: Any = RequestContext(session=session, request_id=1, meta=None, lifespan_context=None)

        # Call sampling callback
        result = await session._summarizing_sampling_callback(context, params)

        # Verify the result is correct
        assert isinstance(result, CreateMessageResult)
        assert result.role == "assistant"
        assert isinstance(result.content, TextContent)
        assert "Message processed with summarization" in result.content.text

        # Verify message was added to history
        assert len(session.history) == 1
        assert session.history[0].role == "user"
        assert isinstance(session.history[0].content, TextContent)
        assert session.history[0].content.text == "Hello world"

    finally:
        await send_stream.aclose()
        await receive_stream.aclose()


@pytest.mark.asyncio
async def test_custom_summary_prompt():
    """Test that user can define custom prompt"""
    send_stream, receive_stream = anyio.create_memory_object_stream(10)
    try:
        custom_prompt = "Custom summary prompt:\n\n"
        session = ClientSessionSummarizing(
            read_stream=receive_stream,
            write_stream=send_stream,
            summary_prompt=custom_prompt,
        )

        # Verify user can define custom prompt
        assert session.summary_prompt == custom_prompt
        assert session.summary_prompt != DEFAULT_SUMMARY_PROMPT

        # Test that summarization uses custom prompt
        session.history = [SamplingMessage(role="user", content=TextContent(type="text", text="Test message"))]

        await session.summarize_context()

        # Verify summary contains custom prompt
        assert len(session.history) == 1
        summary_content = session.history[0].content
        assert isinstance(summary_content, TextContent)
        assert custom_prompt in summary_content.text

    finally:
        await send_stream.aclose()
        await receive_stream.aclose()


@pytest.mark.asyncio
async def test_default_summary_prompt():
    """Test that user gets default prompt if not specified"""
    send_stream, receive_stream = anyio.create_memory_object_stream(10)
    try:
        session = ClientSessionSummarizing(
            read_stream=receive_stream,
            write_stream=send_stream,
        )

        # Verify user gets default prompt
        assert session.summary_prompt == DEFAULT_SUMMARY_PROMPT

    finally:
        await send_stream.aclose()
        await receive_stream.aclose()


@pytest.mark.asyncio
async def test_custom_max_tokens():
    """Test that user can define custom max tokens"""
    send_stream, receive_stream = anyio.create_memory_object_stream(10)
    try:
        custom_max_tokens = 2000
        session = ClientSessionSummarizing(
            read_stream=receive_stream,
            write_stream=send_stream,
            max_tokens=custom_max_tokens,
        )

        # Verify user can define custom max tokens
        assert session.max_tokens == custom_max_tokens
        assert session.max_tokens != DEFAULT_MAX_TOKENS

    finally:
        await send_stream.aclose()
        await receive_stream.aclose()


@pytest.mark.asyncio
async def test_custom_summarize_threshold():
    """Test that user can define custom summarize threshold"""
    send_stream, receive_stream = anyio.create_memory_object_stream(10)
    try:
        custom_threshold = 0.5
        session = ClientSessionSummarizing(
            read_stream=receive_stream,
            write_stream=send_stream,
            summarize_threshold=custom_threshold,
        )

        # Verify user can define custom threshold
        assert session.summarize_threshold == custom_threshold
        assert session.summarize_threshold != DEFAULT_SUMMARIZE_THRESHOLD

    finally:
        await send_stream.aclose()
        await receive_stream.aclose()


@pytest.mark.asyncio
async def test_default_parameters():
    """Test that user gets default parameters if not specified"""
    send_stream, receive_stream = anyio.create_memory_object_stream(10)
    try:
        session = ClientSessionSummarizing(
            read_stream=receive_stream,
            write_stream=send_stream,
        )

        # Verify user gets default parameters
        assert session.max_tokens == DEFAULT_MAX_TOKENS
        assert session.summarize_threshold == DEFAULT_SUMMARIZE_THRESHOLD
        assert session.summary_prompt == DEFAULT_SUMMARY_PROMPT

    finally:
        await send_stream.aclose()
        await receive_stream.aclose()
