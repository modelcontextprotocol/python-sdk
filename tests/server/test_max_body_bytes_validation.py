import pytest

from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http import StreamableHTTPServerTransport


def test_sse_transport_rejects_non_positive_max_body_bytes():
    with pytest.raises(ValueError, match="max_body_bytes must be positive or None"):
        SseServerTransport("/messages/", max_body_bytes=0)


def test_streamable_http_transport_rejects_non_positive_max_body_bytes():
    with pytest.raises(ValueError, match="max_body_bytes must be positive or None"):
        StreamableHTTPServerTransport(mcp_session_id=None, max_body_bytes=0)
