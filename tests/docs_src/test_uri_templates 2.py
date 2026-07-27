"""`docs/servers/uri-templates.md`: every claim the page makes, proved against the real SDK."""

from pathlib import Path

import pytest
from inline_snapshot import snapshot
from mcp_types import INVALID_PARAMS, ErrorData, ResourceTemplate, TextResourceContents

from docs_src.uri_templates import tutorial001, tutorial002, tutorial003, tutorial004, tutorial005
from mcp import Client, MCPError
from mcp.server import MCPServer
from mcp.shared.path_security import PathEscapeError, contains_path_traversal, safe_join
from mcp.shared.uri_template import InvalidUriTemplate, UriTemplate

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_simple_expansion_maps_the_segment_to_the_argument() -> None:
    """tutorial001: `books://{isbn}` reads `books://978-...` and the matched string is the argument."""
    async with Client(tutorial001.mcp) as client:
        (content,) = (await client.read_resource("books://978-0441172719")).contents
        assert isinstance(content, TextResourceContents)
        assert content.text == snapshot('{\n  "title": "Dune",\n  "author": "Frank Herbert"\n}')


async def test_an_int_parameter_is_converted_from_the_uri_string() -> None:
    """tutorial001: `order_id: int` receives `12345`, not `"12345"`, so `order_id + 1` is `12346`."""
    async with Client(tutorial001.mcp) as client:
        (content,) = (await client.read_resource("orders://12345")).contents
        assert isinstance(content, TextResourceContents)
        assert content.text == snapshot('{\n  "order_id": 12345,\n  "next_order": 12346,\n  "status": "shipped"\n}')


async def test_plus_keeps_the_slashes_in_the_captured_value() -> None:
    """tutorial001: `{+path}` matches `printing/setup.md` as one value; a plain `{path}` would not."""
    async with Client(tutorial001.mcp) as client:
        (content,) = (await client.read_resource("manuals://printing/setup.md")).contents
        assert isinstance(content, TextResourceContents)
        assert content.text == "# Printer setup\n\nLoad paper, then power on."


async def test_omitted_query_params_fall_through_to_function_defaults() -> None:
    """tutorial001: `{?limit,sort}` is lenient. No query string means `limit=10, sort="newest"`."""
    async with Client(tutorial001.mcp) as client:
        (content,) = (await client.read_resource("reviews://978-0441172719")).contents
        assert isinstance(content, TextResourceContents)
        assert content.text == "10 newest reviews of Dune"


async def test_a_query_param_overrides_only_the_default_it_names() -> None:
    """tutorial001: `?sort=top` sets `sort` and leaves `limit` at its default."""
    async with Client(tutorial001.mcp) as client:
        (content,) = (await client.read_resource("reviews://978-0441172719?sort=top")).contents
        assert isinstance(content, TextResourceContents)
        assert content.text == "10 top reviews of Dune"


async def test_exploded_path_arrives_as_a_list_of_segments() -> None:
    """tutorial001: `{/path*}` splits `/fiction/sci-fi` into `["fiction", "sci-fi"]`."""
    async with Client(tutorial001.mcp) as client:
        (content,) = (await client.read_resource("shelves://browse/fiction/sci-fi")).contents
        assert isinstance(content, TextResourceContents)
        assert content.text == "catalog > fiction > sci-fi"


def test_two_adjacent_variables_are_rejected_at_parse_time() -> None:
    """'What the parser rejects': nothing separates `path` from `ext`, so the template is refused."""
    with pytest.raises(InvalidUriTemplate) as exc_info:
        UriTemplate.parse("manuals://{+path}{ext}")
    assert str(exc_info.value) == snapshot(
        "Variables 'path' and 'ext' are adjacent with no literal separator; matching cannot "
        "determine where one ends and the other begins. Add a literal between them or use a single variable."
    )


def test_a_self_delimiting_operator_supplies_the_separator() -> None:
    """'What the parser rejects': `{.ext}` contributes the `.` itself, so `{+path}{.ext}` is accepted."""
    template = UriTemplate.parse("manuals://{+path}{.ext}")
    assert template.match("manuals://printing/setup.md") == {"path": "printing/setup", "ext": "md"}


def test_a_second_multi_segment_variable_is_rejected_at_parse_time() -> None:
    """'What the parser rejects': two `{+...}` are ambiguous about which one absorbs an extra segment."""
    with pytest.raises(InvalidUriTemplate) as exc_info:
        UriTemplate.parse("copy://{+source}/to/{+destination}")
    assert str(exc_info.value) == snapshot(
        "Template contains more than one multi-segment variable ({+var}, {#var}, or explode modifier); "
        "matching would be ambiguous"
    )


def test_a_query_parameter_without_a_python_default_is_rejected_at_decoration_time() -> None:
    """'What the parser rejects': a client may omit `{?limit}`, so the bound parameter must declare a default."""
    strict = MCPServer("Bookshop")
    with pytest.raises(ValueError) as exc_info:

        @strict.resource("reviews://{isbn}{?limit}")
        def list_reviews(isbn: str, limit: int) -> None:
            """Reviews of a book."""

    assert str(exc_info.value) == snapshot(
        "Resource 'reviews://{isbn}{?limit}': query parameter(s) ['limit'] have no default value. "
        "A client may omit a {?...}/{&...} query parameter, so the matching handler parameter "
        "must declare a default."
    )


async def test_traversal_is_rejected_before_the_handler_runs() -> None:
    """The `!!! check`: `../` triggers `-32602` "Unknown resource" and `read_manual` is never called."""
    async with Client(tutorial001.mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("manuals://../etc/passwd")
    assert exc_info.value.error == snapshot(
        ErrorData(
            code=INVALID_PARAMS,
            message="Unknown resource: manuals://../etc/passwd",
            data={"uri": "manuals://../etc/passwd"},
        )
    )


def test_dotdot_is_a_component_check_not_a_substring_scan() -> None:
    """The page's prose: `v1.0..v2.0` passes because `..` is not a standalone path segment."""
    assert contains_path_traversal("../etc") is True
    assert contains_path_traversal("v1.0..v2.0") is False


async def test_safe_join_serves_a_file_inside_the_base_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tutorial002: `safe_join(DOCS_ROOT, path).read_text()` returns the file under the base."""
    (tmp_path / "printing").mkdir()
    (tmp_path / "printing" / "setup.md").write_text("# Printer setup")
    monkeypatch.setattr(tutorial002, "DOCS_ROOT", tmp_path)
    async with Client(tutorial002.mcp) as client:
        (content,) = (await client.read_resource("manuals://printing/setup.md")).contents
        assert isinstance(content, TextResourceContents)
        assert content.text == "# Printer setup"


def test_safe_join_raises_when_the_resolved_path_escapes_the_base(tmp_path: Path) -> None:
    """tutorial002: a path that climbs out of `DOCS_ROOT` raises `PathEscapeError`."""
    with pytest.raises(PathEscapeError):
        safe_join(tmp_path, "../etc/passwd")


async def test_exempt_params_lets_an_absolute_path_through() -> None:
    """tutorial003: `exempt_params={"source"}` skips the checks for that one parameter."""
    async with Client(tutorial003.mcp) as client:
        (content,) = (await client.read_resource("imports://preview//srv/incoming/catalog.csv")).contents
        assert isinstance(content, TextResourceContents)
        assert content.text == "Would import from /srv/incoming/catalog.csv"


async def test_server_wide_resource_security_relaxes_every_resource() -> None:
    """tutorial003: `resource_security=ResourceSecurity(reject_path_traversal=False)` exempts the whole server."""
    async with Client(tutorial003.relaxed) as client:
        (content,) = (await client.read_resource("imports://preview/../sibling/catalog.csv")).contents
        assert isinstance(content, TextResourceContents)
        assert content.text == "Would import from ../sibling/catalog.csv"


async def test_lowlevel_static_dispatch_lists_and_reads_by_exact_uri() -> None:
    """tutorial004: the registry is the listing, and a known URI returns its text."""
    async with Client(tutorial004.server) as client:
        listed = (await client.list_resources()).resources
        assert [r.uri for r in listed] == ["config://shop", "status://health"]
        (content,) = (await client.read_resource("status://health")).contents
        assert content == TextResourceContents(uri="status://health", text="ok")


async def test_lowlevel_unknown_uri_raises() -> None:
    """tutorial004: a URI outside the registry raises and surfaces as a protocol error."""
    async with Client(tutorial004.server) as client:
        with pytest.raises(MCPError):
            await client.read_resource("config://missing")


def test_uritemplate_match_returns_a_dict_or_none() -> None:
    """tutorial005: `match()` extracts decoded variables, or `None` when the URI doesn't fit."""
    assert tutorial005.TEMPLATES["manuals"].match("manuals://printing/setup.md") == {"path": "printing/setup.md"}
    assert tutorial005.TEMPLATES["books"].match("manuals://nope") is None


async def test_lowlevel_match_routes_the_request_to_the_right_template() -> None:
    """tutorial005: two templates, one handler. Each concrete URI lands in its own branch."""
    async with Client(tutorial005.server) as client:
        (manual,) = (await client.read_resource("manuals://printing/setup.md")).contents
        assert manual == TextResourceContents(uri="manuals://printing/setup.md", text="# Printer setup")
        (book,) = (await client.read_resource("books://978-0441172719")).contents
        assert book == TextResourceContents(uri="books://978-0441172719", text="Dune by Frank Herbert")


async def test_lowlevel_handler_applies_the_safety_checks_itself() -> None:
    """tutorial005: there is no default policy down here; `read_manual_safely` is the gate."""
    async with Client(tutorial005.server) as client:
        with pytest.raises(MCPError):
            await client.read_resource("manuals://../etc/passwd")
        with pytest.raises(MCPError):
            await client.read_resource("nothing://matches")


async def test_str_of_a_template_round_trips_to_the_original_string() -> None:
    """tutorial005: `str(template)` is the source string, so the listing reuses the parsed templates."""
    assert str(tutorial005.TEMPLATES["manuals"]) == "manuals://{+path}"
    async with Client(tutorial005.server) as client:
        result = await client.list_resource_templates()
        assert result.resource_templates == snapshot(
            [
                ResourceTemplate(name="manuals", uri_template="manuals://{+path}"),
                ResourceTemplate(name="books", uri_template="books://{isbn}"),
            ]
        )
