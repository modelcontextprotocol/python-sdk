"""Test that URL-encoded parameters are decoded in resource templates.

Regression test for https://github.com/modelcontextprotocol/python-sdk/issues/973
"""

from mcp.server.fastmcp.resources import ResourceTemplate


class TestUrlParameterDecoding:
    """Test URL parameter decoding in resource templates."""

    def test_template_matches_decodes_space(self):
        """Test that %20 is decoded to space."""

        def search(query: str) -> str:  # pragma: no cover
            return f"Results for: {query}"

        template = ResourceTemplate.from_function(
            fn=search,
            uri_template="search://{query}",
            name="search",
        )

        params = template.matches("search://hello%20world")
        assert params is not None
        assert params["query"] == "hello world"

    def test_template_matches_decodes_accented_characters(self):
        """Test that %C3%A9 is decoded to e with accent."""

        def search(query: str) -> str:  # pragma: no cover
            return f"Results for: {query}"

        template = ResourceTemplate.from_function(
            fn=search,
            uri_template="search://{query}",
            name="search",
        )

        params = template.matches("search://caf%C3%A9")
        assert params is not None
        assert params["query"] == "café"

    def test_template_matches_decodes_complex_phrase(self):
        """Test complex French phrase from the original issue."""

        def search(query: str) -> str:  # pragma: no cover
            return f"Results for: {query}"

        template = ResourceTemplate.from_function(
            fn=search,
            uri_template="search://{query}",
            name="search",
        )

        params = template.matches("search://stick%20correcteur%20teint%C3%A9%20anti-imperfections")
        assert params is not None
        assert params["query"] == "stick correcteur teinté anti-imperfections"

    def test_template_matches_preserves_plus_sign(self):
        """Test that plus sign remains as plus (not converted to space).

        In URI encoding, %20 is space. Plus-as-space is only for
        application/x-www-form-urlencoded (HTML forms).
        """

        def search(query: str) -> str:  # pragma: no cover
            return f"Results for: {query}"

        template = ResourceTemplate.from_function(
            fn=search,
            uri_template="search://{query}",
            name="search",
        )

        params = template.matches("search://hello+world")
        assert params is not None
        assert params["query"] == "hello+world"
