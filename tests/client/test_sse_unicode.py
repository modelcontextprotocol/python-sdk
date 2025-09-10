"""Test for SSE client Unicode handling."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx_sse import EventSource

from mcp.client.sse import compliant_aiter_sse

pytestmark = pytest.mark.anyio


def create_mock_event_source(data_chunks: list[bytes]) -> EventSource:
    """Create a mock EventSource that yields the given data chunks."""
    event_source = MagicMock(spec=EventSource)
    response = AsyncMock()
    event_source.response = response
    
    async def mock_aiter_bytes() -> AsyncIterator[bytes]:
        for chunk in data_chunks:
            yield chunk
    
    response.aiter_bytes = mock_aiter_bytes
    return event_source


async def test_compliant_aiter_sse_handles_unicode_line_separators():
    """Test that compliant_aiter_sse correctly handles U+2028 and U+2029 characters."""
    
    # Simulate SSE data with U+2028 in JSON content
    # The server sends: event: message\ndata: {"text":"Hello\u2028World"}\n\n
    test_data = [
        b'event: message\n',
        b'data: {"text":"Hello',
        b'\xe2\x80\xa8',  # UTF-8 encoding of U+2028
        b'World"}\n',
        b'\n',
    ]
    
    event_source = create_mock_event_source(test_data)
    
    # Collect events
    events = [event async for event in compliant_aiter_sse(event_source)]
    
    # Should receive one message event
    assert len(events) == 1
    assert events[0].event == "message"
    # The U+2028 should be preserved in the data
    assert '\u2028' in events[0].data
    assert events[0].data == '{"text":"Hello\u2028World"}'


async def test_compliant_aiter_sse_handles_paragraph_separator():
    """Test that compliant_aiter_sse correctly handles U+2029 (PARAGRAPH SEPARATOR)."""
    
    # Simulate SSE data with U+2029
    test_data = [
        b'event: test\ndata: Line1',
        b'\xe2\x80\xa9',  # UTF-8 encoding of U+2029
        b'Line2\n\n',
    ]
    
    event_source = create_mock_event_source(test_data)
    
    events = [event async for event in compliant_aiter_sse(event_source)]
    
    assert len(events) == 1
    assert events[0].event == "test"
    # U+2029 should be preserved, not treated as a newline
    assert '\u2029' in events[0].data
    assert events[0].data == 'Line1\u2029Line2'


async def test_compliant_aiter_sse_handles_crlf():
    """Test that compliant_aiter_sse correctly handles \\r\\n line endings."""
    
    # Simulate SSE data with CRLF line endings
    test_data = [
        b'event: message\r\n',
        b'data: test data\r\n',
        b'\r\n',
    ]
    
    event_source = create_mock_event_source(test_data)
    
    events = [event async for event in compliant_aiter_sse(event_source)]
    
    assert len(events) == 1
    assert events[0].event == "message"
    assert events[0].data == "test data"


async def test_compliant_aiter_sse_handles_split_utf8():
    """Test that compliant_aiter_sse handles UTF-8 characters split across chunks."""
    
    # Split a UTF-8 emoji (🎉 = \xf0\x9f\x8e\x89) across chunks
    test_data = [
        b'event: message\n',
        b'data: Party ',
        b'\xf0\x9f',  # First half of emoji
        b'\x8e\x89',  # Second half of emoji
        b' time!\n\n',
    ]
    
    event_source = create_mock_event_source(test_data)
    
    events = [event async for event in compliant_aiter_sse(event_source)]
    
    assert len(events) == 1
    assert events[0].event == "message"
    assert events[0].data == "Party 🎉 time!"


async def test_compliant_aiter_sse_handles_multiple_events():
    """Test that compliant_aiter_sse correctly handles multiple SSE events."""
    
    # Multiple events with problematic Unicode
    test_data = [
        b'event: first\ndata: Hello\xe2\x80\xa8World\n\n',
        b'event: second\ndata: Test\xe2\x80\xa9Data\n\n',
        b'data: No event name\n\n',
    ]
    
    event_source = create_mock_event_source(test_data)
    
    events = [event async for event in compliant_aiter_sse(event_source)]
    
    assert len(events) == 3
    
    assert events[0].event == "first"
    assert '\u2028' in events[0].data
    
    assert events[1].event == "second"
    assert '\u2029' in events[1].data
    
    # Default event type is "message"
    assert events[2].event == "message"
    assert events[2].data == "No event name"