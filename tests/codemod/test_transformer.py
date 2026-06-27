"""Behaviour of `transform()`, the whole programmatic surface of the codemod.

Every test feeds one module's source through the public API. A property that
must NOT change is asserted as byte-identity against the input; a rewrite is
asserted as the exact v2 output.
"""

import textwrap

import libcst
import pytest
from inline_snapshot import snapshot
from mcp_codemod import transform


def test_from_import_of_a_renamed_module_is_rewritten() -> None:
    """A `from mcp.server.fastmcp import ...` statement is rewritten to import from `mcp.server.mcpserver`."""
    source = "from mcp.server.fastmcp import Context\n"
    assert transform(source).code == snapshot("from mcp.server.mcpserver import Context\n")


def test_from_import_of_a_renamed_submodule_is_rewritten() -> None:
    """A submodule under a renamed package matches by longest prefix, so only the renamed prefix changes
    and the rest of the dotted path is kept."""
    source = "from mcp.server.fastmcp.prompts.base import UserMessage\n"
    assert transform(source).code == snapshot("from mcp.server.mcpserver.prompts.base import UserMessage\n")


def test_plain_import_of_a_renamed_module_is_rewritten() -> None:
    """`import mcp.types` is rewritten to `import mcp_types`, the module's v2 home."""
    source = "import mcp.types\n"
    assert transform(source).code == snapshot("import mcp_types\n")


def test_dotted_usage_of_a_renamed_module_follows_its_import() -> None:
    """A fully dotted reference such as `mcp.types.Tool` is rewritten together with the
    `import mcp.types` statement that binds it, so the rewritten module still resolves."""
    source = textwrap.dedent("""\
        import mcp.types

        tool = mcp.types.Tool(name="x")
        """)
    assert transform(source).code == snapshot(
        """\
import mcp_types

tool = mcp_types.Tool(name="x")
"""
    )


def test_an_aliased_module_import_keeps_the_local_name() -> None:
    """`import mcp.types as t` is rewritten to `import mcp_types as t`; references through the
    alias `t` already name the right module and are left exactly as written."""
    source = textwrap.dedent("""\
        import mcp.types as t

        tool = t.Tool(name="x")
        """)
    assert transform(source).code == snapshot(
        """\
import mcp_types as t

tool = t.Tool(name="x")
"""
    )


def test_from_mcp_import_types_becomes_a_real_import() -> None:
    """`from mcp import types` bound the deleted `mcp.types` submodule, so the codemod
    replaces it with a real `import mcp_types as types` that produces the same local name."""
    result = transform("from mcp import types\n")
    assert result.code == snapshot("import mcp_types as types\n")


def test_from_mcp_import_types_with_an_alias_keeps_the_alias() -> None:
    """`from mcp import types as t` is rewritten to `import mcp_types as t`, preserving
    the local name the rest of the module refers to."""
    result = transform("from mcp import types as t\n")
    assert result.code == snapshot("import mcp_types as t\n")


def test_types_is_split_off_from_other_imported_names() -> None:
    """When `types` is imported alongside other names from `mcp`, only it is split out into
    a separate `import mcp_types as types`; the remaining names stay in the `from mcp import`."""
    result = transform("from mcp import ClientSession, types\n")
    assert result.code == snapshot(
        """\
from mcp import ClientSession
import mcp_types as types
"""
    )


def test_a_from_mcp_import_without_types_is_untouched() -> None:
    """A `from mcp import ...` that does not name `types` is not an import of the deleted
    submodule, so the module is returned byte-for-byte identical."""
    source = textwrap.dedent("""\
        from mcp import ClientSession, StdioServerParameters

        params = StdioServerParameters(command="python")
        session: ClientSession | None = None
        """)
    assert transform(source).code == source


def test_a_star_import_from_mcp_is_untouched() -> None:
    """`from mcp import *` names no specific binding, so there is nothing for the codemod
    to split out and the source is returned identical."""
    source = "from mcp import *\n"
    assert transform(source).code == source


def test_a_relative_import_is_never_touched() -> None:
    """A relative import refers to the user's own package, never the SDK, so
    `from . import types` and `from .types import Tool` come back exactly as written.
    """
    source = textwrap.dedent("""\
        from . import types
        from .types import Tool


        def make() -> Tool:
            return types.Tool(name="echo")
        """)
    assert transform(source).code == source


def test_an_already_migrated_import_is_a_noop() -> None:
    """Running the codemod over code that is already on v2 is a no-op: the v2 import
    paths match none of the rename tables, so nothing is rewritten or reported.
    """
    source = textwrap.dedent("""\
        import mcp_types
        from mcp.server.mcpserver import MCPServer

        mcp = MCPServer("demo")


        @mcp.tool()
        def greet(name: str) -> mcp_types.TextContent:
            return mcp_types.TextContent(type="text", text=f"hi {name}")
        """)
    result = transform(source)
    assert result.code == source
    assert result.diagnostics == []


def test_an_unrelated_third_party_import_is_untouched() -> None:
    """Imports of and references to non-mcp packages are outside every rename table,
    so a module built on pydantic and httpx is returned exactly as written.
    """
    source = textwrap.dedent("""\
        import httpx
        from pydantic import BaseModel


        class Settings(BaseModel):
            url: str


        def fetch(settings: Settings) -> httpx.Response:
            return httpx.get(settings.url)
        """)
    assert transform(source).code == source


def test_a_file_with_no_mcp_usage_is_returned_byte_identical() -> None:
    """A module that never mentions mcp is the do-no-harm contract: the source comes
    back byte-identical with no diagnostics and no rewrites recorded.
    """
    source = textwrap.dedent("""\
        # Shared logging setup for the example application.

        import logging


        def get_logger(name: str) -> logging.Logger:
            \"\"\"Return the logger for `name`.\"\"\"
            return logging.getLogger(name)
        """)
    result = transform(source)
    assert result.code == source
    assert result.diagnostics == []
    assert dict(result.rewrites) == {}


def test_an_unchanged_mcp_module_path_is_not_renamed() -> None:
    """An mcp import path that did not move between v1 and v2 is not rewritten, so
    `mcp.client.streamable_http` and `mcp.server.lowlevel` survive untouched.
    """
    source = textwrap.dedent("""\
        from mcp.client.streamable_http import streamable_http_client
        from mcp.server.lowlevel import Server

        server = Server("demo")


        async def connect(url: str) -> None:
            async with streamable_http_client(url) as (read, write):
                await server.run(read, write)
        """)
    assert transform(source).code == source


def test_a_renamed_class_import_and_every_use_are_rewritten() -> None:
    """Importing `FastMCP` from `mcp.server.fastmcp` rewrites the module path, the imported
    name, and every call site to the v2 `mcp.server.mcpserver.MCPServer` spelling."""
    source = textwrap.dedent("""\
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("demo")
        """)
    assert transform(source).code == snapshot("""\
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("demo")
""")


def test_an_aliased_import_of_a_renamed_symbol_keeps_the_local_alias() -> None:
    """`from mcp.server.fastmcp import FastMCP as F` renames only the imported name; the local
    alias `F` and every use of it are left exactly as written."""
    source = textwrap.dedent("""\
        from mcp.server.fastmcp import FastMCP as F

        mcp = F("demo")
        """)
    assert transform(source).code == snapshot("""\
from mcp.server.mcpserver import MCPServer as F

mcp = F("demo")
""")


def test_a_fully_dotted_reference_to_a_renamed_symbol_is_rewritten() -> None:
    """A fully dotted use such as `mcp.shared.exceptions.McpError` has only its final segment
    renamed to `MCPError`; the `import` statement and the module prefix are untouched."""
    source = textwrap.dedent("""\
        import mcp.shared.exceptions

        raise mcp.shared.exceptions.McpError(1, "x")
        """)
    assert transform(source).code == snapshot("""\
import mcp.shared.exceptions

raise mcp.shared.exceptions.MCPError(1, "x")
""")


def test_a_user_class_sharing_a_renamed_name_is_never_touched() -> None:
    """A user-defined `FastMCP` class in a module with no mcp imports is left identical: the
    rename is keyed on the qualified name resolved through imports, never the bare token."""
    source = textwrap.dedent("""\
        class FastMCP:
            def __init__(self, name):
                self.name = name


        app = FastMCP("demo")
        """)
    assert transform(source).code == source


def test_non_reference_positions_of_a_renamed_name_are_never_rewritten() -> None:
    """Only the import alias is renamed to `MCPServer`; an attribute access `obj.FastMCP` and a
    keyword argument `FastMCP=` are name positions, not references, and keep the v1 spelling."""
    source = textwrap.dedent("""\
        from mcp.server.fastmcp import FastMCP


        def use(obj, g):
            obj.FastMCP
            g(FastMCP=1)
        """)
    assert transform(source).code == snapshot("""\
from mcp.server.mcpserver import MCPServer


def use(obj, g):
    obj.FastMCP
    g(FastMCP=1)
""")


def test_a_removed_function_import_gets_a_marker_and_is_not_rewritten() -> None:
    """`create_connected_server_and_client_session` has no v2 spelling, so the call site
    keeps its v1 name and gains a `manual` diagnostic plus an inline marker comment.
    """
    source = textwrap.dedent("""\
        from mcp.shared.memory import create_connected_server_and_client_session


        async def main(server):
            async with create_connected_server_and_client_session(server) as session:
                await session.list_tools()
        """)
    result = transform(source)
    assert "create_connected_server_and_client_session" in result.code
    assert any(diagnostic.severity == "manual" for diagnostic in result.diagnostics)
    assert "# mcp-codemod:" in result.code


def test_the_websocket_client_import_is_flagged() -> None:
    """The WebSocket transport was deleted from v2, so a `websocket_client` use is flagged
    `manual` at the import and at the call, and the only change to the module is the
    inserted marker comments.
    """
    source = textwrap.dedent("""\
        from mcp.client.websocket import websocket_client


        async def main() -> None:
            async with websocket_client("ws://localhost:3000/ws") as (read, write):
                pass
        """)
    result = transform(source)
    assert any(d.severity == "manual" and "WebSocket" in d.message for d in result.diagnostics)
    assert result.code == snapshot("""\
# mcp-codemod: `mcp.client.websocket.websocket_client` removed: the WebSocket transport was deleted
from mcp.client.websocket import websocket_client


async def main() -> None:
    # mcp-codemod: `mcp.client.websocket.websocket_client` removed: the WebSocket transport was deleted
    async with websocket_client("ws://localhost:3000/ws") as (read, write):
        pass
""")


def test_a_removed_attribute_is_flagged_regardless_of_receiver() -> None:
    """`get_server_capabilities` is matched by attribute name alone -- the codemod cannot
    see a receiver's type -- so the access is flagged `manual` and left exactly as written.
    """
    source = textwrap.dedent("""\
        from mcp import ClientSession


        def capabilities(session: ClientSession) -> object:
            return session.get_server_capabilities()
        """)
    result = transform(source)
    assert any(diagnostic.severity == "manual" for diagnostic in result.diagnostics)
    assert "# mcp-codemod:" in result.code
    assert "session.get_server_capabilities()" in result.code


def test_a_lowlevel_server_decorator_is_flagged_with_its_constructor_kwarg() -> None:
    """A lowlevel `@server.call_tool()` registration cannot be migrated mechanically, so it
    is flagged `manual` with the `on_call_tool=` guidance and the handler is not touched.
    """
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        server = Server("s")


        @server.call_tool()
        async def handle(name: str, arguments: dict):
            return []
        """)
    result = transform(source)
    (diagnostic,) = result.diagnostics
    assert diagnostic.severity == "manual"
    assert "on_call_tool=" in diagnostic.message
    assert "@server.call_tool()\nasync def handle(name: str, arguments: dict):\n    return []\n" in result.code
    assert "# mcp-codemod:" in result.code


def test_a_high_level_decorator_is_never_flagged() -> None:
    """`@mcp.tool()` is syntactically identical to a lowlevel decorator and only the
    receiver's binding tells them apart: the `MCPServer` form gets no diagnostic or marker.
    """
    source = textwrap.dedent("""\
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("d")


        @mcp.tool()
        def add(a: int, b: int) -> int:
            return a + b
        """)
    result = transform(source)
    assert result.diagnostics == []
    assert "# mcp-codemod" not in result.code


def test_a_safe_camelcase_attribute_read_is_renamed() -> None:
    """A safe-tier camelCase field read as an attribute is rewritten to its snake_case spelling.

    The rewrite is reported as a single info diagnostic and never earns an inline marker.
    """
    source = textwrap.dedent("""\
        from mcp.types import CallToolResult


        def show(result: CallToolResult) -> None:
            print(result.structuredContent)
        """)
    result = transform(source)
    assert result.code == snapshot("""\
from mcp_types import CallToolResult


def show(result: CallToolResult) -> None:
    print(result.structured_content)
""")
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["info"]
    assert "# mcp-codemod" not in result.code


def test_a_risky_camelcase_attribute_read_is_renamed_with_a_review_marker() -> None:
    """A risky-tier camelCase field is still renamed, but the rewrite rests on a heuristic.

    It is reported as a single review diagnostic and an inline review marker is inserted above the site.
    """
    source = textwrap.dedent("""\
        from mcp import ClientSession


        async def page(session: ClientSession) -> None:
            result = await session.list_tools()
            print(result.nextCursor)
        """)
    result = transform(source)
    assert result.code == snapshot("""\
from mcp import ClientSession


async def page(session: ClientSession) -> None:
    result = await session.list_tools()
    # mcp-codemod: review: renamed `.nextCursor` to `.next_cursor`; verify the receiver is an mcp type
    print(result.next_cursor)
""")
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["review"]
    assert "# mcp-codemod: review:" in result.code


def test_camelcase_attributes_are_untouched_in_a_file_that_never_imports_mcp() -> None:
    """A file that never imports mcp keeps every camelCase attribute exactly as written.

    The whole camelCase rename is gated on the file importing the SDK at all.
    """
    source = textwrap.dedent("""\
        import json


        def describe(result: object) -> str:
            return json.dumps(result.inputSchema)
        """)
    assert transform(source).code == source


def test_camelcase_names_outside_the_allowlist_are_never_renamed() -> None:
    """camelCase attribute names that v1 `mcp.types` never declared are left exactly as written.

    Only the allowlisted field names are ever considered, so stdlib and user camelCase APIs survive.
    """
    source = textwrap.dedent("""\
        import logging

        import mcp


        def configure(obj: object, level: int) -> None:
            logging.getLogger(__name__).setLevel(level)
            obj.basicConfig()
        """)
    assert transform(source).code == source


def test_camelcase_strings_outside_a_getattr_call_are_never_renamed() -> None:
    """An allowlisted camelCase name spelled as a string -- a dict key, a subscript index, a bare
    literal -- is left exactly as written even though the file imports mcp: camelCase is the wire format.
    """
    source = textwrap.dedent("""\
        from mcp import ClientSession


        def wire(session: ClientSession, schema: object, d: dict[str, object]) -> object:
            payload = {"inputSchema": schema}
            raw = d["inputSchema"]
            name = "inputSchema"
            return payload, raw, name
        """)
    assert transform(source).code == source


def test_camelcase_keywords_on_an_mcp_constructor_are_renamed() -> None:
    """camelCase keyword arguments on a call that resolves into the SDK are rewritten to
    their snake_case spellings, alongside the `mcp.types` -> `mcp_types` import rename."""
    source = textwrap.dedent("""\
        from mcp.types import Tool

        tool = Tool(name="x", inputSchema={}, outputSchema={})
        """)
    assert transform(source).code == snapshot("""\
from mcp_types import Tool

tool = Tool(name="x", input_schema={}, output_schema={})
""")


def test_camelcase_keywords_on_a_call_outside_mcp_are_untouched() -> None:
    """The keyword rename fires only when the callee resolves into the SDK, so an allowlisted
    camelCase keyword passed to the user's own function is left exactly as written."""
    source = textwrap.dedent("""\
        import mcp


        def build(**fields: object) -> dict[str, object]:
            return dict(fields)


        schema = build(inputSchema={})
        """)
    assert transform(source).code == source


def test_a_camelcase_field_in_a_hasattr_string_is_renamed() -> None:
    """An allowlisted camelCase field spelled as a string literal in a `hasattr` call is
    renamed to its snake_case form and reported as an info diagnostic, with no inline marker."""
    source = textwrap.dedent("""\
        from mcp import ClientSession


        def has_structured(result: object) -> bool:
            return hasattr(result, "structuredContent")
        """)
    result = transform(source)
    assert result.code == snapshot("""\
from mcp import ClientSession


def has_structured(result: object) -> bool:
    return hasattr(result, "structured_content")
""")
    assert [(diagnostic.severity, diagnostic.transform) for diagnostic in result.diagnostics] == [
        ("info", "attr_snake_case")
    ]


def test_a_string_outside_the_allowlist_in_a_getattr_call_is_untouched() -> None:
    """A `getattr` string naming an attribute outside the camelCase allowlist is never
    rewritten, so ordinary attribute names survive byte for byte."""
    source = textwrap.dedent("""\
        import mcp


        def tool_name(result: object) -> object:
            return getattr(result, "name")
        """)
    assert transform(source).code == source


def test_a_dynamic_attribute_argument_to_getattr_is_untouched() -> None:
    """A `getattr` whose attribute argument is a variable rather than a string literal is
    left exactly as written: the codemod only rewrites names it can read from the source."""
    source = textwrap.dedent("""\
        import mcp


        def field(result: object, key: str) -> object:
            return getattr(result, key)
        """)
    assert transform(source).code == source


def test_mcperror_wrapping_errordata_is_flattened_to_keyword_arguments() -> None:
    """An `McpError(ErrorData(...))` raise is rewritten to `MCPError(...)` with the
    `ErrorData` fields promoted to direct keyword arguments, and both imports renamed."""
    source = textwrap.dedent("""\
        from mcp.shared.exceptions import McpError
        from mcp.types import ErrorData

        raise McpError(ErrorData(code=1, message="x", data=None))
        """)
    assert transform(source).code == snapshot("""\
from mcp.shared.exceptions import MCPError
from mcp_types import ErrorData

raise MCPError(code=1, message="x", data=None)
""")


def test_mcperror_with_a_non_errordata_argument_is_renamed_and_marked() -> None:
    """`McpError(err)` cannot be unpacked into v2's flat `MCPError(code, message, data)`
    constructor, so the call is renamed and the site is marked rather than left to
    fail with a confusing `TypeError` at the raise."""
    source = textwrap.dedent("""\
        from mcp.shared.exceptions import McpError


        def reraise(err):
            raise McpError(err)
        """)
    result = transform(source)
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["manual"]
    assert "MCPError(code, message, data=None)" in result.diagnostics[0].message
    assert "    # mcp-codemod: " in result.code
    assert "    raise MCPError(err)" in result.code


def test_error_attribute_chains_on_a_caught_mcperror_are_flattened() -> None:
    """Inside `except McpError as e:`, the v1 `e.error.code` / `e.error.message` /
    `e.error.data` chains each collapse to the v2 direct attribute on `e`."""
    source = textwrap.dedent("""\
        from mcp.shared.exceptions import McpError

        try:
            run()
        except McpError as e:
            print(e.error.code, e.error.message, e.error.data)
        """)
    assert transform(source).code == snapshot("""\
from mcp.shared.exceptions import MCPError

try:
    run()
except MCPError as e:
    print(e.code, e.message, e.data)
""")


def test_a_bare_error_attribute_on_a_caught_mcperror_is_not_collapsed() -> None:
    """A bare `e.error` inside `except McpError as e:` may be a whole `ErrorData`
    being passed somewhere, so it is never collapsed to `e`."""
    source = textwrap.dedent("""\
        from mcp.shared.exceptions import McpError

        try:
            run()
        except McpError as e:
            handle(e.error)
        """)
    assert "handle(e.error)" in transform(source).code


def test_error_chains_outside_a_mcperror_handler_are_untouched() -> None:
    """An `e.error.code` chain only collapses inside an `except McpError as e:` handler;
    at module level and inside an `except ValueError as e:` it is left as written."""
    source = textwrap.dedent("""\
        from mcp.shared.exceptions import McpError

        e = current_error()
        top = e.error.code
        try:
            run()
        except ValueError as e:
            low = e.error.code
        """)
    result = transform(source)
    assert "top = e.error.code" in result.code
    assert "low = e.error.code" in result.code


def test_a_mcperror_handler_without_a_binding_does_not_flatten() -> None:
    """An `except McpError:` clause with no `as` name leaves an `<obj>.error.<field>` chain in its
    body byte-unchanged: without a bound name there is nothing to key the flatten on.
    """
    source = textwrap.dedent("""\
        from mcp import McpError

        try:
            run()
        except McpError:
            log(err.error.code)
        """)
    result = transform(source)
    # The handler type itself was recognized (and renamed), so the non-flatten is not vacuous.
    assert "except MCPError:" in result.code
    assert "err.error.code" in result.code


def test_nested_handlers_track_the_innermost_binding() -> None:
    """Only the name bound by the innermost enclosing `except McpError as ...:` is flattened; once
    that nested handler is left, the enclosing non-McpError handler's binding is not treated as one.
    """
    source = textwrap.dedent("""\
        from mcp import McpError

        try:
            run()
        except ValueError as e:
            try:
                run()
            except McpError as inner:
                log(inner.error.code)
            log(e.error.code)
        """)
    assert transform(source).code == snapshot("""\
from mcp import MCPError

try:
    run()
except ValueError as e:
    try:
        run()
    except MCPError as inner:
        log(inner.code)
    log(e.error.code)
""")


def test_a_syntax_error_raises_parser_syntax_error() -> None:
    """Source that is not parseable as Python raises `libcst.ParserSyntaxError`, the one exception
    `transform()` documents.
    """
    with pytest.raises(libcst.ParserSyntaxError):
        transform("def (")


def test_the_three_tuple_unpack_is_narrowed_to_two() -> None:
    """The v1 `streamable_http_client` context manager yielded a third `get_session_id` value that v2 no longer
    returns, so a three-element `as` tuple is narrowed to the first two.
    """
    source = textwrap.dedent("""\
        from mcp.client.streamable_http import streamable_http_client


        async def main(url: str) -> None:
            async with streamable_http_client(url) as (read, write, _):
                pass
        """)
    assert transform(source).code == snapshot(
        """\
from mcp.client.streamable_http import streamable_http_client


async def main(url: str) -> None:
    async with streamable_http_client(url) as (read, write):
        pass
"""
    )


def test_a_named_third_element_gets_a_marker_when_dropped() -> None:
    """When the dropped third element was bound to a real name rather than `_`, later uses of that name will break,
    so the narrowing also raises a manual diagnostic naming the removed `get_session_id` value.
    """
    source = textwrap.dedent("""\
        from mcp.client.streamable_http import streamable_http_client


        async def main(url: str) -> None:
            async with streamable_http_client(url) as (read, write, get_id):
                pass
        """)
    result = transform(source)
    assert "as (read, write):" in result.code
    [diagnostic] = result.diagnostics
    assert diagnostic.severity == "manual"
    assert "get_session_id" in diagnostic.message


def test_removed_client_keywords_each_get_a_marker() -> None:
    """v2's `streamable_http_client` no longer accepts `headers=`, `timeout=`, or `auth=`. Each one gets its own
    manual diagnostic, and the keywords are left in place rather than silently deleted.
    """
    source = textwrap.dedent("""\
        from mcp.client.streamable_http import streamable_http_client


        async def main(url: str, h: dict[str, str], a: object) -> None:
            async with streamable_http_client(url, headers=h, timeout=5, auth=a) as (read, write):
                pass
        """)
    result = transform(source)
    assert [(diagnostic.severity, diagnostic.message.partition(" ")[0]) for diagnostic in result.diagnostics] == [
        ("manual", "`headers=`"),
        ("manual", "`timeout=`"),
        ("manual", "`auth=`"),
    ]
    assert "streamable_http_client(url, headers=h, timeout=5, auth=a)" in result.code


def test_the_deprecated_streamablehttp_client_alias_is_renamed() -> None:
    """The old `streamablehttp_client` spelling becomes `streamable_http_client` at both the import and the call
    site, and the same with-item's three-element `as` tuple is narrowed in the same pass.
    """
    source = textwrap.dedent("""\
        from mcp.client.streamable_http import streamablehttp_client


        async def main(url: str) -> None:
            async with streamablehttp_client(url) as (a, b, _):
                pass
        """)
    assert transform(source).code == snapshot(
        """\
from mcp.client.streamable_http import streamable_http_client


async def main(url: str) -> None:
    async with streamable_http_client(url) as (a, b):
        pass
"""
    )


def test_a_two_tuple_unpack_is_already_correct() -> None:
    """A two-element `as` tuple is already the v2 shape, so the module round-trips byte-for-byte: re-running the
    codemod on already-migrated code is a no-op for this transform.
    """
    source = textwrap.dedent("""\
        from mcp.client.streamable_http import streamable_http_client


        async def main(url: str) -> None:
            async with streamable_http_client(url) as (read, write):
                pass
        """)
    assert transform(source).code == source


def test_a_non_tuple_as_target_is_untouched() -> None:
    """A transport client with-item bound to a single name rather than a tuple is left exactly as written.

    Only the 3-tuple `as (read, write, get_session_id)` shape has a third element to drop.
    """
    source = textwrap.dedent("""\
        from mcp.client.streamable_http import streamable_http_client


        async def main(url: str) -> None:
            async with streamable_http_client(url) as transport:
                print(transport)
    """)
    assert transform(source).code == source


def test_an_unrelated_context_manager_is_untouched() -> None:
    """A with-statement whose item is not an mcp transport client is never rewritten.

    `open()` resolves to a builtin and a bare lock is not even a call, so both round-trip unchanged.
    """
    source = textwrap.dedent("""\
        import threading

        import mcp

        lock = threading.Lock()


        def main(path: str) -> None:
            with open(path) as f:
                f.read()
            with lock:
                pass
    """)
    assert transform(source).code == source


def test_an_unimported_transport_name_is_never_touched() -> None:
    """A bare `streamable_http_client` that was never imported does not resolve to the mcp transport client.

    The codemod refuses to act on a name it cannot resolve, so the 3-tuple with-item is left exactly as written.
    """
    source = textwrap.dedent("""\
        from mcp import ClientSession


        async def main(url: str) -> None:
            async with streamable_http_client(url) as (read, write, get_session_id):
                print(read, write, get_session_id)
    """)
    assert transform(source).code == source


def test_a_transport_keyword_on_the_constructor_gets_a_marker_and_stays() -> None:
    """A transport keyword on the constructor is flagged as manual work but never deleted.

    Where the kwarg belongs on v2 depends on how the server is started, so the codemod
    leaves the configuration in place rather than silently dropping it.
    """
    source = textwrap.dedent("""\
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("d", stateless_http=True, port=1)
        """)
    result = transform(source)
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["manual", "manual"]
    assert "stateless_http=True" in result.code
    assert "port=1" in result.code


def test_a_removed_constructor_keyword_gets_a_marker() -> None:
    """A constructor keyword that v2 removed outright gets a manual diagnostic naming it."""
    source = textwrap.dedent("""\
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("d", mount_path="/x")
        """)
    result = transform(source)
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["manual"]
    assert "mount_path" in result.diagnostics[0].message


def test_surviving_constructor_keywords_are_not_flagged() -> None:
    """A constructor keyword that still exists on the v2 `MCPServer` produces no diagnostic.

    `dependencies`, `debug`, and `log_level` are here deliberately: a flag on a
    keyword that still works tells the user a lie they cannot reconcile, so the
    keywords v2 kept must never be in the moved or removed tables.
    """
    source = textwrap.dedent("""\
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("d", instructions="hi", dependencies=["a"], debug=False, log_level="INFO")
        """)
    assert transform(source).diagnostics == []


def test_a_lowlevel_server_bound_to_an_attribute_is_not_tracked() -> None:
    """Only a plain-name binding of a lowlevel `Server(...)` is tracked, so a registration
    on a server held in an instance attribute is left alone with no diagnostic."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server


        class Holder:
            def __init__(self) -> None:
                self.s = Server("x")

                @self.s.call_tool()
                async def handle(name, arguments):
                    return []
        """)
    assert transform(source).diagnostics == []


def test_transforming_already_transformed_code_is_a_noop() -> None:
    """Running the codemod over its own output changes nothing, even for a source that exercises
    a module rename, a symbol rename, a camelCase attribute rename, and a flag-only diagnostic.
    """
    source = textwrap.dedent("""\
        from mcp import McpError
        from mcp.types import Tool


        def describe(tool: Tool, server: object) -> object:
            server.get_context()
            schema = tool.inputSchema
            if schema is None:
                raise McpError("missing schema")
            return schema
        """)
    once = transform(source)
    assert once.code != source
    assert transform(once.code).code == once.code


def test_a_marker_is_not_duplicated_on_a_second_run() -> None:
    """A second run over already-marked output recognises the existing `# mcp-codemod:` comment
    and does not insert it again.
    """
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        server = Server("demo")
        result = server.get_server_capabilities()
        """)
    once = transform(source)
    assert transform(once.code).code.count("# mcp-codemod:") == 1


def test_add_markers_false_reports_without_inserting_comments() -> None:
    """With `add_markers=False` a flag-only finding still appears in `diagnostics`, but no
    `# mcp-codemod` comment is written into the code.
    """
    source = textwrap.dedent("""\
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("demo", port=9000)
        """)
    result = transform(source, add_markers=False)
    assert "# mcp-codemod" not in result.code
    assert result.diagnostics


def test_a_marker_on_a_decorated_function_lands_above_the_decorators() -> None:
    """The marker for a flagged lowlevel `@server.call_tool()` registration is inserted above the
    decorator line, not between the decorator and the `def`.
    """
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        server = Server("example")


        @server.call_tool()
        async def handle_call_tool(name: str, arguments: dict[str, str]) -> list[str]:
            return [name]
        """)
    lines = transform(source).code.splitlines()
    marker_index = next(i for i, line in enumerate(lines) if "# mcp-codemod:" in line)
    assert marker_index < lines.index("@server.call_tool()")


def test_info_diagnostics_never_produce_a_marker() -> None:
    """A safe camelCase attribute rename is reported as an `info` diagnostic only; no
    `# mcp-codemod` comment is added for it.
    """
    source = textwrap.dedent("""\
        from mcp.types import Tool


        def schema_of(tool: Tool) -> object:
            return tool.inputSchema
        """)
    result = transform(source)
    assert result.diagnostics
    assert all(diagnostic.severity == "info" for diagnostic in result.diagnostics)
    assert "# mcp-codemod" not in result.code


def test_a_dotted_module_usage_is_counted_as_one_rewrite() -> None:
    """`import mcp.types` plus one `mcp.types.X` reference is two logical rewrites, not
    three: only the innermost node naming the module is replaced, so the visitor never
    double-counts the attribute chain that encloses it.
    """
    result = transform("import mcp.types\n\nx: mcp.types.Tool\n")
    assert result.code == "import mcp_types\n\nx: mcp_types.Tool\n"
    assert result.rewrites["module_rename"] == 2


def test_a_local_variable_named_mcp_is_never_treated_as_the_package() -> None:
    """`mcp = MCPServer(...)` is the most common variable name in real MCP code, so an
    attribute chain on it that happens to spell a module path must never be rewritten.
    Only a name that resolves through an import is.
    """
    source = "mcp = build()\nprint(mcp.types)\n"
    assert transform(source).code == source


def test_a_semicolon_joined_statement_line_is_left_as_written() -> None:
    """A `from mcp import types` joined to another statement by a semicolon cannot be
    split out into its own `import mcp_types as types` line, so the whole statement
    is left exactly as written rather than half-rewritten.
    """
    source = "DEBUG = True; from mcp import types\n"
    assert transform(source).code == source


def test_camelcase_keywords_on_a_local_variable_named_mcp_are_untouched() -> None:
    """A local variable named `mcp` is the most common name in real MCP code; keyword
    arguments on a method call through it must never be renamed when nothing in the
    file actually imports the SDK.
    """
    source = 'mcp = Router()\nmcp.register(inputSchema={"a": 1}, isError=False)\n'
    result = transform(source)
    assert result.code == source
    assert result.diagnostics == []


def test_a_getattr_string_in_a_file_that_never_imports_mcp_is_untouched() -> None:
    """The string form of the camelCase rename is gated on the file importing the SDK,
    exactly like the attribute form, so an ORM lookup elsewhere is never rewritten.
    """
    source = 'value = getattr(row, "createdAt", None)\n'
    assert transform(source).code == source


def test_a_risky_camelcase_getattr_string_gets_a_review_marker() -> None:
    """A risky-tier name renamed inside a `getattr` string is marked for review, the
    same way the equivalent attribute access is.
    """
    source = 'import mcp\n\ncursor = getattr(result, "nextCursor", None)\n'
    result = transform(source)
    assert '"next_cursor"' in result.code
    assert "# mcp-codemod: review:" in result.code


def test_removed_attribute_names_are_untouched_in_a_file_that_never_imports_mcp() -> None:
    """`get_context` is a common method name well outside MCP; a file that never
    imports the SDK must never have a removal marker written into it.
    """
    source = textwrap.dedent("""\
        class DetailView(View):
            def render(self):
                return self.get_context()
        """)
    result = transform(source)
    assert result.code == source
    assert result.diagnostics == []


def test_renaming_a_plain_import_still_needed_for_other_names_gets_a_review_marker() -> None:
    """`import mcp.types` also bound the name `mcp`. When another reference still
    needs that binding (and no other import provides it), the rewrite to
    `import mcp_types` is marked for review.
    """
    source = textwrap.dedent("""\
        import httpx
        import mcp.types

        tool = mcp.types.Tool(name="x", input_schema={})
        session = mcp.ClientSession(read, write, client=httpx.AsyncClient())
        """)
    result = transform(source)
    assert "import mcp_types\n" in result.code
    assert "mcp_types.Tool" in result.code
    assert "# mcp-codemod: review:" in result.code
    assert "add `import mcp` back" in result.code


def test_renaming_a_plain_import_whose_binding_nothing_else_needs_is_silent() -> None:
    """When every reference through `import mcp.types` is itself being rewritten,
    losing the `mcp` binding breaks nothing, so no review marker is added.
    """
    source = 'import mcp.types\n\ntool = mcp.types.Tool(name="x", input_schema={})\n'
    result = transform(source)
    assert result.code == 'import mcp_types\n\ntool = mcp_types.Tool(name="x", input_schema={})\n'
    assert result.diagnostics == []


def test_a_dotted_usage_through_a_bare_import_mcp_is_marked_not_rewritten() -> None:
    """`import mcp` plus `mcp.types.X` is valid v1, but rewriting the usage would leave
    nothing importing `mcp_types`, so the site is marked and left exactly as written.
    """
    source = 'import mcp\n\ntool = mcp.types.Tool(name="x")\n'
    result = transform(source)
    assert "mcp.types.Tool" in result.code
    assert "mcp_types.Tool" not in result.code
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["manual"]
    assert "import `mcp_types`" in result.diagnostics[0].message


def test_a_renamed_module_imported_from_its_parent_package_is_split_out() -> None:
    """`from mcp.server import fastmcp` bound the renamed module to a local name, the
    same shape as `from mcp import types`, so it becomes a real import of the new
    module under the same local name.
    """
    assert transform("from mcp.server import fastmcp\n").code == snapshot("import mcp.server.mcpserver as fastmcp\n")


def test_constructor_flags_fire_for_every_import_path_of_the_renamed_class() -> None:
    """`from mcp.server import FastMCP` is a real v1 spelling, so its constructor gets
    the same moved- and removed-keyword markers as the `mcp.server.fastmcp` spelling.
    """
    source = textwrap.dedent("""\
        from mcp.server import FastMCP

        mcp = FastMCP("demo", port=8000, mount_path="/old")
        """)
    result = transform(source)
    assert "MCPServer" in result.code
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["manual", "manual"]


def test_a_renamed_symbol_reached_through_a_module_alias_is_rewritten() -> None:
    """A renamed class accessed as an attribute of an aliased module import is still
    resolved through the import, so both the import and the access are rewritten.
    """
    source = textwrap.dedent("""\
        import mcp.server.fastmcp as fm

        mcp = fm.FastMCP("demo")
        """)
    assert transform(source).code == snapshot(
        """\
import mcp.server.mcpserver as fm

mcp = fm.MCPServer("demo")
"""
    )


def test_an_import_of_a_types_name_with_no_v2_home_is_marked() -> None:
    """`mcp_types` is not a name-superset of v1's `mcp.types`: a name with no v2
    home (`Cursor`) is marked at the import and at every use, never silently
    rewritten into an import that cannot resolve.
    """
    source = textwrap.dedent("""\
        from mcp.types import Cursor, Tool

        cursor: Cursor | None = None
        """)
    result = transform(source)
    assert "from mcp_types import Cursor, Tool" in result.code
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["manual", "manual"]
    assert all("`mcp.types.Cursor` removed" in diagnostic.message for diagnostic in result.diagnostics)


def test_a_removed_api_reached_through_its_module_is_marked() -> None:
    """A removed API spelled `module.symbol` gets the same marker as the bare
    imported name; `leave_Name` only ever sees the latter.
    """
    source = textwrap.dedent("""\
        from mcp.shared import memory

        streams = memory.create_connected_server_and_client_session(server)
        """)
    result = transform(source)
    assert "# mcp-codemod:" in result.code
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["manual"]
    assert "create_connected_server_and_client_session" in result.diagnostics[0].message


def test_a_plain_import_of_a_deeper_renamed_module_is_not_double_flagged() -> None:
    """`import mcp.server.fastmcp.server` also resolves its own `mcp.server.fastmcp`
    prefix; only the full path is rewritten and the prefix must not be flagged.
    """
    source = "import mcp.server.fastmcp.server\n\nctx = mcp.server.fastmcp.server.Context()\n"
    result = transform(source)
    assert result.code == "import mcp.server.mcpserver.server\n\nctx = mcp.server.mcpserver.server.Context()\n"
    assert result.diagnostics == []


def test_transport_client_kwargs_are_flagged_in_any_call_form() -> None:
    """The removed client keywords and the narrower yield are marked even when the
    call is not itself the `with` item; `enter_async_context` is the common form.
    """
    source = textwrap.dedent("""\
        from mcp.client.streamable_http import streamablehttp_client


        async def connect(stack, url):
            return await stack.enter_async_context(streamablehttp_client(url, headers={"x": "y"}))
        """)
    result = transform(source)
    assert "streamable_http_client(url, headers" in result.code
    assert sorted(d.transform for d in result.diagnostics) == ["transport_client_param", "transport_client_unpack"]


def test_an_already_migrated_client_call_outside_a_with_is_never_flagged() -> None:
    """A call through the v2 name proves nothing about its surroundings being v1,
    so already-migrated code never gets the yield-shape marker.
    """
    source = textwrap.dedent("""\
        from mcp.client.streamable_http import streamable_http_client


        async def connect(stack, url):
            return await stack.enter_async_context(streamable_http_client(url))
        """)
    result = transform(source)
    assert result.code == source
    assert result.diagnostics == []


def test_two_identical_findings_on_one_statement_produce_one_marker() -> None:
    """Two findings with the same message on one statement collapse into a single
    inline comment; each is still reported as its own diagnostic.
    """
    source = "import mcp\n\nflag = a.isError or b.isError\n"
    result = transform(source)
    assert result.code.count("# mcp-codemod:") == 1
    assert len(result.diagnostics) == 2


def test_an_assignment_to_a_caught_error_field_is_never_collapsed() -> None:
    """`e.error.message = ...` works on v2 (`MCPError.error` is still a mutable
    `ErrorData`), but `e.message = ...` would not -- `message` became a read-only
    property -- so only the READ of the chain is collapsed, never a write target.
    """
    source = textwrap.dedent("""\
        from mcp import McpError

        try:
            run()
        except McpError as e:
            e.error.message = "while syncing: " + e.error.message
            raise
        """)
    result = transform(source)
    assert 'e.error.message = "while syncing: " + e.message' in result.code
    assert result.diagnostics == []


def test_a_nested_handler_does_not_hide_the_caught_mcperror() -> None:
    """A nested `try`/`except` inside an `except McpError as e:` handler does not
    re-bind `e`, so `e.error.code` in the nested body is still collapsed.
    """
    source = textwrap.dedent("""\
        from mcp import McpError

        try:
            run()
        except McpError as e:
            try:
                cleanup()
            except:
                log(e.error.code)
        """)
    assert "log(e.code)" in transform(source).code


def test_a_tuple_except_clause_binding_mcperror_is_recognized() -> None:
    """`except (McpError, ValueError) as e:` binds `e` to a possible `McpError`, so the
    exception types and the `e.error.code` read are both rewritten.
    """
    source = textwrap.dedent("""\
        from mcp import McpError

        try:
            run()
        except (McpError, ValueError) as e:
            log(e.error.code)
        """)
    result = transform(source)
    assert "except (MCPError, ValueError) as e:" in result.code
    assert "log(e.code)" in result.code


def test_a_v1_client_with_item_bound_to_a_single_name_is_flagged() -> None:
    """`async with streamablehttp_client(...) as streams:` cannot have its unpacking
    rewritten (it happens somewhere else), so the call gets the yield-shape marker.
    """
    source = textwrap.dedent("""\
        from mcp.client.streamable_http import streamablehttp_client


        async def connect(url):
            async with streamablehttp_client(url) as streams:
                read, write, _ = streams
        """)
    result = transform(source)
    assert "streamable_http_client(url) as streams:" in result.code
    assert [diagnostic.transform for diagnostic in result.diagnostics] == ["transport_client_unpack"]


def test_an_annotated_lowlevel_server_assignment_is_recognized() -> None:
    """`server: Server = Server(...)` binds the server exactly like the un-annotated
    form, so its decorators get the same lowlevel registration marker.
    """
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        server: Server = Server("demo")


        @server.call_tool()
        async def handle(name, arguments):
            return []
        """)
    result = transform(source)
    assert [diagnostic.transform for diagnostic in result.diagnostics] == ["lowlevel_decorator"]
    assert "on_call_tool=" in result.diagnostics[0].message


def test_camelcase_attributes_are_renamed_in_a_file_importing_only_mcp_types() -> None:
    """A half-migrated file whose only SDK import is already `mcp_types` still gets
    the attribute renames; `import mcp_types` is as much the SDK as `import mcp`.
    """
    source = textwrap.dedent("""\
        import mcp_types


        def show(result: mcp_types.CallToolResult) -> None:
            print(result.structuredContent)
        """)
    assert "result.structured_content" in transform(source).code


def test_the_v2_request_context_idiom_is_never_flagged() -> None:
    """`ctx.request_context.lifespan_context` is a live, documented v2 idiom. The
    lowlevel `Server.request_context` property was also removed, but a name-only
    match cannot tell the two apart, so neither is flagged.
    """
    source = textwrap.dedent("""\
        from mcp.server.fastmcp import Context, FastMCP


        async def query(ctx: Context) -> object:
            return ctx.request_context.lifespan_context.db
        """)
    result = transform(source)
    assert "ctx.request_context.lifespan_context.db" in result.code
    assert result.diagnostics == []


def test_a_trailing_comment_on_a_split_import_is_kept() -> None:
    """The whole-statement rewrite of `from mcp import types` keeps the original
    line's trailing comment -- a `# noqa` there is load-bearing.
    """
    assert transform("from mcp import types  # noqa: F401\n").code == snapshot(
        "import mcp_types as types  # noqa: F401\n"
    )


def test_a_marker_on_the_first_statement_is_not_duplicated_on_a_rerun() -> None:
    """A comment above a module's FIRST statement parses into the module header, not
    the statement, so the re-run dedup has to look there too.
    """
    source = "# Application entrypoint.\nfrom mcp.client.websocket import websocket_client\n"
    once = transform(source).code
    assert once.count("# mcp-codemod:") == 1
    assert transform(once).code == once


def test_an_empty_module_is_returned_unchanged() -> None:
    """An empty file is valid input and comes back empty with nothing reported."""
    result = transform("")
    assert result.code == ""
    assert result.diagnostics == []


def test_positional_constructor_arguments_after_the_name_are_flagged() -> None:
    """v1's second positional was `instructions`; v2's is `title`. Renaming the call
    and leaving the argument would silently send the instructions as the title, so
    every positional after the name is marked instead.
    """
    source = textwrap.dedent("""\
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("demo", "Use these instructions to call my tools.")
        """)
    result = transform(source)
    assert "MCPServer(" in result.code
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["manual"]
    assert "`title` is now second" in result.diagnostics[0].message


def test_an_attribute_also_declared_by_a_class_in_the_file_is_marked_not_renamed() -> None:
    """A file can declare an allowlisted camelCase name on its own model (mirroring
    the wire format). Renaming its uses would break that class, so nothing is
    rewritten and each use is marked for the reader to split.
    """
    source = textwrap.dedent("""\
        from pydantic import BaseModel

        import mcp_types


        class Row(BaseModel):
            inputSchema: dict[str, object]


        def show(row: Row) -> None:
            print(row.inputSchema)
        """)
    result = transform(source)
    assert "row.inputSchema" in result.code
    assert "row.input_schema" not in result.code
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["manual"]
    assert "declared by a class in this file" in result.diagnostics[0].message


def test_a_super_init_call_in_an_mcperror_subclass_is_flattened() -> None:
    """`super().__init__(ErrorData(...))` inside a `McpError` subclass is the same v1
    constructor reached the one way a qualified name cannot see, so it gets the same
    flatten as a direct `McpError(ErrorData(...))` call.
    """
    source = textwrap.dedent("""\
        from mcp import McpError
        from mcp.types import INVALID_PARAMS, ErrorData


        class ToolInputError(McpError):
            def __init__(self, message: str) -> None:
                super().__init__(ErrorData(code=INVALID_PARAMS, message=message))
        """)
    result = transform(source)
    assert "super().__init__(code=INVALID_PARAMS, message=message)" in result.code
    assert "class ToolInputError(MCPError):" in result.code


def test_a_super_init_call_with_a_variable_argument_is_marked() -> None:
    """`super().__init__(err)` in a `McpError` subclass cannot be unpacked, so it is
    marked exactly like `McpError(err)` rather than left to fail when first raised.
    """
    source = textwrap.dedent("""\
        from mcp import McpError


        class WrappedError(McpError):
            def __init__(self, err) -> None:
                super().__init__(err)
        """)
    result = transform(source)
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["manual"]
    assert "MCPError(code, message, data=None)" in result.diagnostics[0].message


def test_a_removed_nested_class_reached_through_its_parent_is_marked() -> None:
    """`RequestParams.Meta` is a nested class with no v2 home; the qualified-name
    check sees the whole dotted path even though the per-module name tests cannot.
    """
    source = textwrap.dedent("""\
        from mcp.types import RequestParams

        meta = RequestParams.Meta(progressToken="t")
        """)
    result = transform(source)
    severities = [diagnostic.severity for diagnostic in result.diagnostics]
    assert "manual" in severities
    assert any("RequestParamsMeta" in diagnostic.message for diagnostic in result.diagnostics)


def test_the_server_submodule_import_targets_the_v2_submodule() -> None:
    """`mcp.server.fastmcp.server` maps to the literal v2 submodule, where every one
    of its public names (`Settings` is the giveaway -- the package does not export
    it) still lives.
    """
    source = "from mcp.server.fastmcp.server import Context, Settings\n"
    assert transform(source).code == snapshot("from mcp.server.mcpserver.server import Context, Settings\n")


def test_a_resolvable_non_mcp_receiver_is_never_flagged() -> None:
    """A receiver the imports prove is another package (`multiprocessing.get_context`)
    is never name-matched, however mcp-flavoured the attribute name looks.
    """
    source = textwrap.dedent("""\
        import multiprocessing

        from mcp.server.mcpserver import MCPServer

        ctx = multiprocessing.get_context("spawn")
        """)
    result = transform(source)
    assert result.code == source
    assert result.diagnostics == []


def test_no_unbind_marker_when_another_import_keeps_the_root_bound() -> None:
    """Renaming `import mcp.types` cannot unbind `mcp` while another plain import
    of an `mcp.` module survives, so no review marker is added.
    """
    source = textwrap.dedent("""\
        import mcp.client.session
        import mcp.types

        session = mcp.client.session.ClientSession(read, write)
        tool = mcp.types.Tool(name="x", input_schema={})
        """)
    result = transform(source)
    assert "import mcp_types" in result.code
    assert "mcp_types.Tool" in result.code
    assert result.diagnostics == []
