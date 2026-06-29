"""Regression tests for https://github.com/modelcontextprotocol/python-sdk/issues/973 (URL-encoded template params)."""

from mcp.server.mcpserver.resources import ResourceTemplate


def test_template_matches_decodes_space():
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


def test_template_matches_decodes_accented_characters():
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


def test_template_matches_decodes_complex_phrase():
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


def test_template_matches_preserves_plus_sign():
    # Plus-as-space is only for application/x-www-form-urlencoded; in URI encoding space is %20.
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
