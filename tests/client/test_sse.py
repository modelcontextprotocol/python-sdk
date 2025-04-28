import pytest
from mcp.client.sse import custom_url_join


@pytest.mark.parametrize(
    "base_url,endpoint,expected",
    [
        # Additional test cases to verify behavior with different URL structures
        (
            "https://mcp.example.com/weather/sse",
            "/messages/?session_id=616df71373444d76bd566df4377c9629",
            "https://mcp.example.com/weather/messages/?session_id=616df71373444d76bd566df4377c9629",
        ),
        (
            "https://mcp.example.com/weather/clarksburg/sse",
            "/messages/?session_id=616df71373444d76bd566df4377c9629",
            "https://mcp.example.com/weather/clarksburg/messages/?session_id=616df71373444d76bd566df4377c9629",
        ),
        (
            "https://mcp.example.com/sse",
            "/messages/?session_id=616df71373444d76bd566df4377c9629",
            "https://mcp.example.com/messages/?session_id=616df71373444d76bd566df4377c9629",
        ),
    ],
)
def test_custom_url_join(base_url, endpoint, expected):
    """Test the custom_url_join function with messages endpoint and session ID."""
    result = custom_url_join(base_url, endpoint)
    assert result == expected
