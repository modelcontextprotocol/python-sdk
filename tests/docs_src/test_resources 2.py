"""`docs/servers/resources.md`: every claim the page makes, proved against the real SDK."""

import base64

import pytest
from inline_snapshot import snapshot
from mcp_types import BlobResourceContents, Resource, ResourceTemplate, TextResourceContents

from docs_src.resources import tutorial001, tutorial002, tutorial003
from mcp import Client
from mcp.server import MCPServer

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_function_becomes_a_listed_resource() -> None:
    """tutorial001: the URI, the function name and the docstring are the whole listing entry."""
    async with Client(tutorial001.mcp) as client:
        (resource,) = (await client.list_resources()).resources
        assert resource == snapshot(
            Resource(
                name="get_config",
                uri="config://app",
                description="The active shop configuration.",
                mime_type="text/plain",
            )
        )


async def test_read_returns_the_return_value_as_text() -> None:
    """tutorial001: reading the URI runs the function and wraps the `str` in `TextResourceContents`."""
    async with Client(tutorial001.mcp) as client:
        result = await client.read_resource("config://app")
        assert result.contents == [
            TextResourceContents(uri="config://app", mime_type="text/plain", text="theme=dark\nlanguage=en")
        ]


async def test_template_is_listed_separately_from_resources() -> None:
    """tutorial002: a `{placeholder}` moves the entry from `resources/list` to `resources/templates/list`."""
    async with Client(tutorial002.mcp) as client:
        assert [r.uri for r in (await client.list_resources()).resources] == ["config://app"]
        (template,) = (await client.list_resource_templates()).resource_templates
        assert template == snapshot(
            ResourceTemplate(
                name="get_user_profile",
                uri_template="users://{user_id}/profile",
                description="A customer's profile.",
                mime_type="text/plain",
            )
        )


async def test_reading_a_template_fills_the_placeholder() -> None:
    """tutorial002: the client reads a concrete URI; the matched value arrives as the function argument."""
    async with Client(tutorial002.mcp) as client:
        result = await client.read_resource("users://42/profile")
        assert result.contents == [
            TextResourceContents(
                uri="users://42/profile", mime_type="text/plain", text="User 42: 12 orders since 2021."
            )
        ]


def test_uri_params_must_match_function_params() -> None:
    """The `!!! check`: a placeholder/parameter mismatch is rejected at decoration time, not at read time."""
    broken = MCPServer("Bookshop")
    with pytest.raises(ValueError) as exc_info:

        @broken.resource("users://{user_id}/profile")
        def get_user_profile(user: str) -> None:
            """A customer's profile."""

    assert str(exc_info.value) == snapshot(
        "Mismatch between URI parameters {'user_id'} and function parameters {'user'}"
    )


async def test_mime_type_is_what_you_declare() -> None:
    """tutorial003: `mime_type=` lands in the listing verbatim; the SDK never guesses it from the value."""
    async with Client(tutorial003.mcp) as client:
        resources = (await client.list_resources()).resources
        assert {r.uri: r.mime_type for r in resources} == snapshot(
            {
                "docs://readme": "text/markdown",
                "stats://catalog": "application/json",
                "covers://placeholder": "image/gif",
            }
        )


async def test_str_return_is_sent_as_is() -> None:
    """tutorial003: a `str` return value is the text content, untouched."""
    async with Client(tutorial003.mcp) as client:
        (content,) = (await client.read_resource("docs://readme")).contents
        assert isinstance(content, TextResourceContents)
        assert content.text == "# Bookshop\n\nSearch the catalog with the `search_books` tool."


async def test_dict_return_becomes_json_text() -> None:
    """tutorial003: a non-`str`, non-`bytes` return value is serialised to JSON text."""
    async with Client(tutorial003.mcp) as client:
        (content,) = (await client.read_resource("stats://catalog")).contents
        assert isinstance(content, TextResourceContents)
        assert content.text == snapshot('{\n  "books": 1204,\n  "authors": 391\n}')


async def test_bytes_return_becomes_a_blob() -> None:
    """tutorial003: a `bytes` return value arrives as `BlobResourceContents`, base64-encoded in `blob`."""
    async with Client(tutorial003.mcp) as client:
        (content,) = (await client.read_resource("covers://placeholder")).contents
        assert isinstance(content, BlobResourceContents)
        assert content == BlobResourceContents(
            uri="covers://placeholder",
            mime_type="image/gif",
            blob="R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7",
        )
        assert base64.b64decode(content.blob) == tutorial003.placeholder_cover()
