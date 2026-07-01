"""Behaviour of `transform()`, the whole programmatic surface of the codemod.

Properties that must not change are asserted byte-identical to the input; rewrites as exact v2 output.
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
    """A submodule under a renamed package matches by longest prefix; the rest of the dotted path is kept."""
    source = "from mcp.server.fastmcp.prompts.base import UserMessage\n"
    assert transform(source).code == snapshot("from mcp.server.mcpserver.prompts.base import UserMessage\n")


def test_plain_import_of_a_renamed_module_is_rewritten() -> None:
    """`import mcp.types` is rewritten to `import mcp_types`, the module's v2 home."""
    source = "import mcp.types\n"
    assert transform(source).code == snapshot("import mcp_types\n")


def test_dotted_usage_of_a_renamed_module_follows_its_import() -> None:
    """A dotted reference like `mcp.types.Tool` is rewritten together with the import that binds it."""
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
    """`import mcp.types as t` becomes `import mcp_types as t`; references through the alias are untouched."""
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
    """`from mcp import types` becomes `import mcp_types as types`, keeping the same local name."""
    result = transform("from mcp import types\n")
    assert result.code == snapshot("import mcp_types as types\n")


def test_from_mcp_import_types_with_an_alias_keeps_the_alias() -> None:
    """`from mcp import types as t` becomes `import mcp_types as t`."""
    result = transform("from mcp import types as t\n")
    assert result.code == snapshot("import mcp_types as t\n")


def test_types_is_split_off_from_other_imported_names() -> None:
    """Only `types` is split out of a mixed `from mcp import`; the other names stay put."""
    result = transform("from mcp import ClientSession, types\n")
    assert result.code == snapshot(
        """\
from mcp import ClientSession
import mcp_types as types
"""
    )


def test_a_from_mcp_import_without_types_is_untouched() -> None:
    """A `from mcp import ...` that does not name `types` round-trips byte-identical."""
    source = textwrap.dedent("""\
        from mcp import ClientSession, StdioServerParameters

        params = StdioServerParameters(command="python")
        session: ClientSession | None = None
        """)
    assert transform(source).code == source


def test_a_star_import_from_mcp_is_untouched() -> None:
    """`from mcp import *` names no specific binding, so there is nothing to split out."""
    source = "from mcp import *\n"
    assert transform(source).code == source


def test_a_relative_import_is_never_touched() -> None:
    """A relative import refers to the user's own package, never the SDK."""
    source = textwrap.dedent("""\
        from . import types
        from .types import Tool


        def make() -> Tool:
            return types.Tool(name="echo")
        """)
    assert transform(source).code == source


def test_an_already_migrated_import_is_a_noop() -> None:
    """Code already on v2 is a no-op: nothing is rewritten or reported."""
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
    """Non-mcp imports and references are outside every rename table."""
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
    """The do-no-harm contract: a module that never mentions mcp comes back byte-identical."""
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
    """An mcp import path that did not move between v1 and v2 is not rewritten."""
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
    """A `FastMCP` import rewrites the module path, the imported name, and every call site."""
    source = textwrap.dedent("""\
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("demo")
        """)
    assert transform(source).code == snapshot("""\
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("demo")
""")


def test_an_aliased_import_of_a_renamed_symbol_keeps_the_local_alias() -> None:
    """Only the imported name is renamed; the local alias and its uses are untouched."""
    source = textwrap.dedent("""\
        from mcp.server.fastmcp import FastMCP as F

        mcp = F("demo")
        """)
    assert transform(source).code == snapshot("""\
from mcp.server.mcpserver import MCPServer as F

mcp = F("demo")
""")


def test_a_fully_dotted_reference_to_a_renamed_symbol_is_rewritten() -> None:
    """A dotted use has only its final segment renamed; the import and module prefix are untouched."""
    source = textwrap.dedent("""\
        import mcp.shared.exceptions

        raise mcp.shared.exceptions.McpError(1, "x")
        """)
    assert transform(source).code == snapshot("""\
import mcp.shared.exceptions

raise mcp.shared.exceptions.MCPError(1, "x")
""")


def test_a_user_class_sharing_a_renamed_name_is_never_touched() -> None:
    """The rename is keyed on the qualified name resolved through imports, never the bare token."""
    source = textwrap.dedent("""\
        class FastMCP:
            def __init__(self, name):
                self.name = name


        app = FastMCP("demo")
        """)
    assert transform(source).code == source


def test_non_reference_positions_of_a_renamed_name_are_never_rewritten() -> None:
    """`obj.FastMCP` and `FastMCP=` are name positions, not references, and keep the v1 spelling."""
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
    """A removed function keeps its v1 name and gains a manual diagnostic plus an inline marker."""
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
    """A `websocket_client` use is flagged manual at the import and the call; only markers are inserted."""
    source = textwrap.dedent("""\
        from mcp.client.websocket import websocket_client


        async def main() -> None:
            async with websocket_client("ws://localhost:3000/ws") as (read, write):
                pass
        """)
    result = transform(source)
    assert any(d.severity == "manual" and "WebSocket" in d.message for d in result.diagnostics)
    assert result.code == snapshot("""\
# mcp-codemod: `mcp.client.websocket` removed: the WebSocket transport was deleted
from mcp.client.websocket import websocket_client


async def main() -> None:
    # mcp-codemod: `mcp.client.websocket.websocket_client` removed: the WebSocket transport was deleted
    async with websocket_client("ws://localhost:3000/ws") as (read, write):
        pass
""")


def test_a_removed_attribute_is_flagged_regardless_of_receiver() -> None:
    """A removed attribute is matched by name alone (receiver types are invisible), flagged, and kept."""
    source = textwrap.dedent("""\
        from mcp import ClientSession


        def capabilities(session: ClientSession) -> object:
            return session.get_server_capabilities()
        """)
    result = transform(source)
    assert any(diagnostic.severity == "manual" for diagnostic in result.diagnostics)
    assert "# mcp-codemod:" in result.code
    assert "session.get_server_capabilities()" in result.code


def test_a_call_tool_decorator_site_is_rewritten_with_full_v1_dispatch() -> None:
    """The adapter carries v1's whole dispatch: tool cache, input validation, and the isError contract."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        server = Server("s")


        @server.call_tool()
        async def handle(name: str, arguments: dict):
            return []
        """)
    result = transform(source)
    assert "async def handle(name: str, arguments: dict):\n    return []\n" in result.code
    assert "_server_tool_cache" in result.code
    assert "jsonschema.validate(instance=arguments" in result.code
    assert 'server.add_request_handler("tools/call", mcp_types.CallToolRequestParams, _handle_handler)' in result.code
    assert "import jsonschema" in result.code
    assert "# mcp-codemod:" not in result.code


def test_a_high_level_decorator_is_never_flagged() -> None:
    """Only the receiver's binding separates `@mcp.tool()` from a lowlevel decorator; it gets no flag."""
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
    """A safe-tier camelCase read is renamed, reported as info, and never earns an inline marker."""
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
    """A risky-tier camelCase rename is reported as review, with an inline marker above the site."""
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
    """The camelCase rename is gated on the file importing the SDK at all."""
    source = textwrap.dedent("""\
        import json


        def describe(result: object) -> str:
            return json.dumps(result.inputSchema)
        """)
    assert transform(source).code == source


def test_camelcase_names_outside_the_allowlist_are_never_renamed() -> None:
    """Only allowlisted field names are ever considered, so stdlib and user camelCase APIs survive."""
    source = textwrap.dedent("""\
        import logging

        import mcp


        def configure(obj: object, level: int) -> None:
            logging.getLogger(__name__).setLevel(level)
            obj.basicConfig()
        """)
    assert transform(source).code == source


def test_camelcase_strings_outside_a_getattr_call_are_never_renamed() -> None:
    """String spellings outside `getattr`/`hasattr` are left alone: camelCase is the wire format."""
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
    """camelCase keywords on a call that resolves into the SDK are renamed to snake_case."""
    source = textwrap.dedent("""\
        from mcp.types import Tool

        tool = Tool(name="x", inputSchema={}, outputSchema={})
        """)
    assert transform(source).code == snapshot("""\
from mcp_types import Tool

tool = Tool(name="x", input_schema={}, output_schema={})
""")


def test_camelcase_keywords_on_a_call_outside_mcp_are_untouched() -> None:
    """The keyword rename fires only when the callee resolves into the SDK."""
    source = textwrap.dedent("""\
        import mcp


        def build(**fields: object) -> dict[str, object]:
            return dict(fields)


        schema = build(inputSchema={})
        """)
    assert transform(source).code == source


def test_a_camelcase_field_in_a_hasattr_string_is_renamed() -> None:
    """A camelCase string in a `hasattr` call is renamed and reported as info, with no marker."""
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
    """A `getattr` string outside the camelCase allowlist is never rewritten."""
    source = textwrap.dedent("""\
        import mcp


        def tool_name(result: object) -> object:
            return getattr(result, "name")
        """)
    assert transform(source).code == source


def test_a_dynamic_attribute_argument_to_getattr_is_untouched() -> None:
    """The codemod only rewrites names it can read from the source; a variable argument is untouched."""
    source = textwrap.dedent("""\
        import mcp


        def field(result: object, key: str) -> object:
            return getattr(result, key)
        """)
    assert transform(source).code == source


def test_a_single_argument_mcperror_call_becomes_from_error_data() -> None:
    """A one-argument `McpError(...)` call converts to `MCPError.from_error_data(...)` as written."""
    source = textwrap.dedent("""\
        from mcp.shared.exceptions import McpError
        from mcp.types import ErrorData

        raise McpError(ErrorData(code=1, message="x", data=None))
        """)
    assert transform(source).code == snapshot("""\
from mcp.shared.exceptions import MCPError
from mcp_types import ErrorData

raise MCPError.from_error_data(ErrorData(code=1, message="x", data=None))
""")


def test_a_mcperror_call_with_a_non_inline_argument_is_rewritten_without_a_marker() -> None:
    """`McpError(err)` needs no unpacking under `from_error_data`, so it is rewritten without a marker."""
    source = textwrap.dedent("""\
        from mcp.shared.exceptions import McpError

        def reraise(err):
            raise McpError(err)
        """)
    result = transform(source)
    assert "raise MCPError.from_error_data(err)" in result.code
    assert result.diagnostics == []


def test_a_dotted_mcperror_call_converts_on_its_full_spelling() -> None:
    """The `from_error_data` conversion composes with the symbol rename on a dotted spelling."""
    source = textwrap.dedent("""\
        import mcp.shared.exceptions

        raise mcp.shared.exceptions.McpError(build_error())
        """)
    result = transform(source)
    assert "raise mcp.shared.exceptions.MCPError.from_error_data(build_error())" in result.code


def test_error_attribute_chains_on_a_caught_error_are_left_alone() -> None:
    """`e.error.code` and friends still work on v2, so only the exception name changes."""
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
    print(e.error.code, e.error.message, e.error.data)
""")


def test_a_syntax_error_raises_parser_syntax_error() -> None:
    """Unparseable source raises `libcst.ParserSyntaxError`, the one exception `transform()` documents."""
    with pytest.raises(libcst.ParserSyntaxError):
        transform("def (")


def test_the_three_tuple_unpack_is_narrowed_to_two() -> None:
    """v2 no longer yields the third `get_session_id` value, so a 3-tuple `as` target narrows to two."""
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
    """Dropping a real name (not `_`) breaks later uses, so the narrowing also raises a manual diagnostic."""
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
    """Each removed client keyword gets its own manual diagnostic; none are silently deleted."""
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
    """The alias renames at the import and the call, and the 3-tuple `as` target narrows in the same pass."""
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
    """A two-element `as` tuple is already the v2 shape, so the module round-trips byte-identical."""
    source = textwrap.dedent("""\
        from mcp.client.streamable_http import streamable_http_client


        async def main(url: str) -> None:
            async with streamable_http_client(url) as (read, write):
                pass
        """)
    assert transform(source).code == source


def test_a_non_tuple_as_target_is_untouched() -> None:
    """Only the 3-tuple `as` shape has a third element to drop; a single-name target is untouched."""
    source = textwrap.dedent("""\
        from mcp.client.streamable_http import streamable_http_client


        async def main(url: str) -> None:
            async with streamable_http_client(url) as transport:
                print(transport)
    """)
    assert transform(source).code == source


def test_an_unrelated_context_manager_is_untouched() -> None:
    """A with-item that is not an mcp transport client is never rewritten."""
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
    """The codemod refuses to act on a name it cannot resolve through an import."""
    source = textwrap.dedent("""\
        from mcp import ClientSession


        async def main(url: str) -> None:
            async with streamable_http_client(url) as (read, write, get_session_id):
                print(read, write, get_session_id)
    """)
    assert transform(source).code == source


def test_a_transport_keyword_on_the_constructor_gets_a_marker_and_stays() -> None:
    """A transport keyword is flagged but never deleted: where it belongs on v2 depends on server startup."""
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
    """A keyword that still exists on the v2 `MCPServer` produces no diagnostic: a flag on a working
    keyword is a lie the user cannot reconcile."""
    source = textwrap.dedent("""\
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("d", instructions="hi", dependencies=["a"], debug=False, log_level="INFO")
        """)
    assert transform(source).diagnostics == []


def test_transforming_already_transformed_code_is_a_noop() -> None:
    """Running the codemod over its own output changes nothing."""
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
    """A second run recognises an existing `# mcp-codemod:` comment and does not insert it again."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        server = Server("demo")
        result = server.get_server_capabilities()
        """)
    once = transform(source)
    assert transform(once.code).code.count("# mcp-codemod:") == 1


def test_add_markers_false_reports_without_inserting_comments() -> None:
    """With `add_markers=False` findings still appear in `diagnostics` but no comment is written."""
    source = textwrap.dedent("""\
        from mcp.server.fastmcp import FastMCP

        app = FastMCP("demo", port=9000)
        """)
    result = transform(source, add_markers=False)
    assert "# mcp-codemod" not in result.code
    assert result.diagnostics


def test_a_marker_on_a_decorated_function_lands_above_the_decorators() -> None:
    """The marker lands above the decorator line, not between the decorator and the `def`."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        server = Server("example")


        @server.call_tool()
        def handle_call_tool(name: str, arguments: dict[str, str]) -> list[str]:
            return [name]
        """)
    lines = transform(source).code.splitlines()
    marker_index = next(i for i, line in enumerate(lines) if "# mcp-codemod:" in line)
    assert marker_index < lines.index("@server.call_tool()")


def test_info_diagnostics_never_produce_a_marker() -> None:
    """An info diagnostic never earns a `# mcp-codemod` comment."""
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
    """Only the innermost node naming the module is replaced, so the enclosing chain is not double-counted."""
    result = transform("import mcp.types\n\nx: mcp.types.Tool\n")
    assert result.code == "import mcp_types\n\nx: mcp_types.Tool\n"
    assert result.rewrites["module_rename"] == 2


def test_a_local_variable_named_mcp_is_never_treated_as_the_package() -> None:
    """`mcp` is the most common variable name in real MCP code; only a name bound by an import is rewritten."""
    source = "mcp = build()\nprint(mcp.types)\n"
    assert transform(source).code == source


def test_a_semicolon_joined_statement_line_is_left_as_written() -> None:
    """A semicolon-joined import cannot be split out, so the statement is left whole rather than half-rewritten."""
    source = "DEBUG = True; from mcp import types\n"
    assert transform(source).code == source


def test_camelcase_keywords_on_a_local_variable_named_mcp_are_untouched() -> None:
    """Keywords on a call through a local `mcp` variable are untouched when nothing imports the SDK."""
    source = 'mcp = Router()\nmcp.register(inputSchema={"a": 1}, isError=False)\n'
    result = transform(source)
    assert result.code == source
    assert result.diagnostics == []


def test_a_getattr_string_in_a_file_that_never_imports_mcp_is_untouched() -> None:
    """The string form of the camelCase rename is gated on an SDK import, like the attribute form."""
    source = 'value = getattr(row, "createdAt", None)\n'
    assert transform(source).code == source


def test_a_risky_camelcase_getattr_string_gets_a_review_marker() -> None:
    """A risky-tier rename inside a `getattr` string is marked for review, like the attribute form."""
    source = 'import mcp\n\ncursor = getattr(result, "nextCursor", None)\n'
    result = transform(source)
    assert '"next_cursor"' in result.code
    assert "# mcp-codemod: review:" in result.code


def test_removed_attribute_names_are_untouched_in_a_file_that_never_imports_mcp() -> None:
    """A file that never imports the SDK must never gain a removal marker."""
    source = textwrap.dedent("""\
        class DetailView(View):
            def render(self):
                return self.get_context()
        """)
    result = transform(source)
    assert result.code == source
    assert result.diagnostics == []


def test_renaming_a_plain_import_still_needed_for_other_names_gets_a_review_marker() -> None:
    """`import mcp.types` also bound `mcp`; the rewrite is marked when another reference still needs that binding."""
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
    """When every reference through the import is itself rewritten, losing the `mcp` binding breaks nothing."""
    source = 'import mcp.types\n\ntool = mcp.types.Tool(name="x", input_schema={})\n'
    result = transform(source)
    assert result.code == 'import mcp_types\n\ntool = mcp_types.Tool(name="x", input_schema={})\n'
    assert result.diagnostics == []


def test_a_dotted_usage_through_a_bare_import_mcp_is_marked_not_rewritten() -> None:
    """Rewriting the usage would leave nothing importing `mcp_types`, so the site is marked instead."""
    source = 'import mcp\n\ntool = mcp.types.Tool(name="x")\n'
    result = transform(source)
    assert "mcp.types.Tool" in result.code
    assert "mcp_types.Tool" not in result.code
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["manual"]
    assert "import `mcp_types`" in result.diagnostics[0].message


def test_a_renamed_module_imported_from_its_parent_package_is_split_out() -> None:
    """`from mcp.server import fastmcp` becomes a real import of the new module under the same local name."""
    assert transform("from mcp.server import fastmcp\n").code == snapshot("import mcp.server.mcpserver as fastmcp\n")


def test_constructor_flags_fire_for_every_import_path_of_the_renamed_class() -> None:
    """Every v1 import spelling of the renamed class gets the same constructor keyword markers."""
    source = textwrap.dedent("""\
        from mcp.server import FastMCP

        mcp = FastMCP("demo", port=8000, mount_path="/old")
        """)
    result = transform(source)
    assert "MCPServer" in result.code
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["manual", "manual"]


def test_a_renamed_symbol_reached_through_a_module_alias_is_rewritten() -> None:
    """A renamed class reached through a module alias rewrites at both the import and the access."""
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
    """A types name with no v2 home is marked, never silently rewritten into an import that cannot resolve."""
    source = textwrap.dedent("""\
        from mcp.types import Cursor, Tool

        cursor: Cursor | None = None
        """)
    result = transform(source)
    assert "from mcp_types import Cursor, Tool" in result.code
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["manual", "manual"]
    assert all("`mcp.types.Cursor` removed" in diagnostic.message for diagnostic in result.diagnostics)


def test_a_removed_api_reached_through_its_module_is_marked() -> None:
    """A removed API spelled `module.symbol` gets the same marker as the bare imported name."""
    source = textwrap.dedent("""\
        from mcp.shared import memory

        streams = memory.create_connected_server_and_client_session(server)
        """)
    result = transform(source)
    assert "# mcp-codemod:" in result.code
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["manual"]
    assert "create_connected_server_and_client_session" in result.diagnostics[0].message


def test_a_plain_import_of_a_deeper_renamed_module_is_not_double_flagged() -> None:
    """Only the full path is rewritten; its renamed prefix must not also be flagged."""
    source = "import mcp.server.fastmcp.server\n\nctx = mcp.server.fastmcp.server.Context()\n"
    result = transform(source)
    assert result.code == "import mcp.server.mcpserver.server\n\nctx = mcp.server.mcpserver.server.Context()\n"
    assert result.diagnostics == []


def test_transport_client_kwargs_are_flagged_in_any_call_form() -> None:
    """Client keyword and yield-shape markers fire even when the call is not itself the `with` item."""
    source = textwrap.dedent("""\
        from mcp.client.streamable_http import streamablehttp_client


        async def connect(stack, url):
            return await stack.enter_async_context(streamablehttp_client(url, headers={"x": "y"}))
        """)
    result = transform(source)
    assert "streamable_http_client(url, headers" in result.code
    assert sorted(d.transform for d in result.diagnostics) == ["transport_client_param", "transport_client_unpack"]


def test_an_already_migrated_client_call_outside_a_with_is_never_flagged() -> None:
    """A call through the v2 name proves nothing about v1 surroundings, so no yield-shape marker."""
    source = textwrap.dedent("""\
        from mcp.client.streamable_http import streamable_http_client


        async def connect(stack, url):
            return await stack.enter_async_context(streamable_http_client(url))
        """)
    result = transform(source)
    assert result.code == source
    assert result.diagnostics == []


def test_two_identical_findings_on_one_statement_produce_one_marker() -> None:
    """Identical findings on one statement collapse into one comment but stay separate diagnostics."""
    source = "import mcp\n\nflag = a.isError or b.isError\n"
    result = transform(source)
    assert result.code.count("# mcp-codemod:") == 1
    assert len(result.diagnostics) == 2


def test_a_v1_client_with_item_bound_to_a_single_name_is_flagged() -> None:
    """A single-name `as` target hides the unpacking, so the call gets the yield-shape marker."""
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
    """An annotated assignment binds the server exactly like the un-annotated form."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        server: Server = Server("demo")


        @server.call_tool()
        async def handle(name, arguments):
            return []
        """)
    result = transform(source)
    assert result.rewrites["lowlevel_registration"] == 1
    assert "# mcp-codemod:" not in result.code


def test_camelcase_attributes_are_renamed_in_a_file_importing_only_mcp_types() -> None:
    """`import mcp_types` is as much the SDK as `import mcp` for gating the attribute renames."""
    source = textwrap.dedent("""\
        import mcp_types


        def show(result: mcp_types.CallToolResult) -> None:
            print(result.structuredContent)
        """)
    assert "result.structured_content" in transform(source).code


def test_the_v2_request_context_idiom_is_never_flagged() -> None:
    """A name-only match cannot tell the removed `Server.request_context` from the live idiom; neither is flagged."""
    source = textwrap.dedent("""\
        from mcp.server.fastmcp import Context, FastMCP


        async def query(ctx: Context) -> object:
            return ctx.request_context.lifespan_context.db
        """)
    result = transform(source)
    assert "ctx.request_context.lifespan_context.db" in result.code
    assert result.diagnostics == []


def test_a_trailing_comment_on_a_split_import_is_kept() -> None:
    """The whole-statement rewrite keeps the trailing comment -- a `# noqa` there is load-bearing."""
    assert transform("from mcp import types  # noqa: F401\n").code == snapshot(
        "import mcp_types as types  # noqa: F401\n"
    )


def test_a_marker_on_the_first_statement_is_not_duplicated_on_a_rerun() -> None:
    """A comment above the first statement parses into the module header; the dedup must look there too."""
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
    """v1's second positional was `instructions`, v2's is `title`; leaving it would silently swap meaning."""
    source = textwrap.dedent("""\
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("demo", "Use these instructions to call my tools.")
        """)
    result = transform(source)
    assert "MCPServer(" in result.code
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["manual"]
    assert "`title` is now second" in result.diagnostics[0].message


def test_an_attribute_also_declared_by_a_class_in_the_file_is_marked_not_renamed() -> None:
    """Renaming uses of a camelCase field that a class in this file also declares would break that class."""
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
    """A subclass `super().__init__(ErrorData(...))` gets the same flatten as a direct `McpError` call."""
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
    """A variable argument cannot be unpacked, so the site is marked rather than left to fail at raise time."""
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
    """The qualified-name check sees the whole dotted path to a removed nested class."""
    source = textwrap.dedent("""\
        from mcp.types import RequestParams

        meta = RequestParams.Meta(progressToken="t")
        """)
    result = transform(source)
    severities = [diagnostic.severity for diagnostic in result.diagnostics]
    assert "manual" in severities
    assert any("RequestParamsMeta" in diagnostic.message for diagnostic in result.diagnostics)


def test_the_server_submodule_import_targets_the_v2_submodule() -> None:
    """Module-level names stay on the v2 submodule; `Context` alone is rehomed to the package."""
    source = "from mcp.server.fastmcp.server import Context, Settings\n"
    assert transform(source).code == snapshot(
        """\
from mcp.server.mcpserver.server import Settings
from mcp.server.mcpserver import Context
"""
    )


def test_a_resolvable_non_mcp_receiver_is_never_flagged() -> None:
    """A receiver the imports prove is another package is never name-matched."""
    source = textwrap.dedent("""\
        import multiprocessing

        from mcp.server.mcpserver import MCPServer

        ctx = multiprocessing.get_context("spawn")
        """)
    result = transform(source)
    assert result.code == source
    assert result.diagnostics == []


def test_no_unbind_marker_when_another_import_keeps_the_root_bound() -> None:
    """Another surviving plain `mcp.` import keeps the root bound, so no review marker is added."""
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


def test_an_import_of_a_removed_module_is_marked_and_kept() -> None:
    """An import of a deleted module is kept as written and marked with the replacement guidance."""
    source = "import mcp.shared.progress\n"
    result = transform(source)
    assert "import mcp.shared.progress\n" in result.code
    assert [diagnostic.transform for diagnostic in result.diagnostics] == ["removed_module"]
    assert "ctx.report_progress()" in result.diagnostics[0].message


def test_a_from_import_out_of_a_removed_namespace_gets_one_marker() -> None:
    """One whole-statement marker; per-name markers would only repeat it."""
    source = "from mcp.shared.experimental.tasks import InMemoryTaskStore, task_execution\n"
    result = transform(source)
    assert result.code.count("# mcp-codemod:") == 1
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["manual"]
    assert "has no replacement" in result.diagnostics[0].message


def test_a_removed_module_imported_from_its_parent_package_is_marked() -> None:
    """The per-name check resolves a module bound through its parent against the removed roots."""
    source = "from mcp.client import websocket\n"
    result = transform(source)
    assert result.code.count("# mcp-codemod:") == 1
    assert "`mcp.client.websocket` removed" in result.diagnostics[0].message


def test_context_imported_from_the_server_module_is_rehomed_to_the_package() -> None:
    """Importing `Context` from `server.py` would be private usage on v2, so it is split out to the package."""
    source = "from mcp.server.fastmcp.server import Context, FastMCP, Settings\n"
    assert transform(source).code == snapshot(
        """\
from mcp.server.mcpserver.server import MCPServer, Settings
from mcp.server.mcpserver import Context
"""
    )


def test_a_rehomed_import_keeps_its_alias_and_takes_the_statement_over_when_alone() -> None:
    """A lone rehomed name replaces the whole statement, `as` alias and all."""
    source = "from mcp.server.fastmcp.server import Context as Ctx\n"
    assert transform(source).code == snapshot("from mcp.server.mcpserver import Context as Ctx\n")


def test_request_context_on_a_proven_lowlevel_server_is_flagged() -> None:
    """Only a receiver the pre-pass proved holds a lowlevel `Server` is flagged, sparing the live v2 idiom."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        server = Server("git")


        async def progress(token: str) -> None:
            ctx = server.request_context
            await ctx.session.send_progress_notification(token, 1.0)
        """)
    result = transform(source)
    assert "server.request_context" in result.code
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["manual"]
    assert "handlers now receive `ctx` explicitly" in result.diagnostics[0].message


def test_a_lowlevel_server_bound_to_an_attribute_is_recognized() -> None:
    """An attribute binding gets the same treatment as a plain name binding."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server


        class App:
            def __init__(self) -> None:
                self.server = Server("demo")

            def current(self) -> object:
                return self.server.request_context
        """)
    result = transform(source)
    assert [diagnostic.severity for diagnostic in result.diagnostics] == ["manual"]
    assert "handlers now receive `ctx` explicitly" in result.diagnostics[0].message


def test_a_marker_survives_a_statement_split() -> None:
    """A flag on an import that is also being split lands above the split's first piece."""
    result = transform("from mcp.server import websocket, fastmcp\n")
    assert result.code == snapshot(
        """\
# mcp-codemod: `mcp.server.websocket` removed: the WebSocket transport was deleted
from mcp.server import websocket
import mcp.server.mcpserver as fastmcp
"""
    )


def test_a_tuple_assignment_involving_a_server_call_is_passed_over() -> None:
    """A tuple target has no single dotted spelling to track, so the pre-pass records nothing."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        primary, label = Server("a"), "main"
        """)
    result = transform(source)
    assert result.code == source
    assert result.diagnostics == []


def test_unpacking_a_call_result_is_passed_over() -> None:
    """An unpacked call result has no single dotted spelling to track, so the pre-pass records nothing."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        server, transport = build(Server("x"))
        """)
    result = transform(source)
    assert result.code == source
    assert result.diagnostics == []


def test_lowlevel_server_positional_arguments_become_keywords() -> None:
    """v2 keeps v1's parameter names and order but makes them keyword-only, so positionals convert one for one."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        server = Server("srv", "1.2.0", "does things")
        """)
    result = transform(source)
    assert 'Server("srv", version="1.2.0", instructions="does things")' in result.code
    assert result.diagnostics == []


def test_a_lowlevel_server_call_with_a_splat_is_left_for_v2_to_reject() -> None:
    """A `*`-splat hides how many positions it fills; v2's own TypeError at construction is loud enough."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        server = Server("srv", *extra)
        """)
    assert transform(source).code == source


def test_lowlevel_keyword_arguments_are_never_touched() -> None:
    """A v1 call already passing keywords is valid v2; nothing changes."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        server = Server("srv", version="1.2.0")
        """)
    assert transform(source).code == source


def test_a_module_level_decorator_site_is_rewritten_to_registration_at_site() -> None:
    """The user's function survives byte-identical; the adapter and registration land at the decorator's position."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server
        import mcp.types as types

        app = Server("demo")

        @app.list_prompts()
        async def list_prompts() -> list[types.Prompt]:
            return []

        run(app)
        """)
    result = transform(source)
    assert result.code == snapshot("""\
from typing import cast
from mcp.server import ServerRequestContext
import mcp_types
from mcp.server.lowlevel import Server
import mcp_types as types

app = Server("demo")

async def list_prompts() -> list[types.Prompt]:
    return []


async def _list_prompts_handler(
    ctx: ServerRequestContext, params: mcp_types.PaginatedRequestParams
) -> mcp_types.ListPromptsResult:
    result = cast("object", await list_prompts())
    if isinstance(result, mcp_types.ListPromptsResult):
        return result
    return mcp_types.ListPromptsResult(prompts=cast("list[mcp_types.Prompt]", result))


app.add_request_handler("prompts/list", mcp_types.PaginatedRequestParams, _list_prompts_handler)

run(app)
""")
    assert result.rewrites["lowlevel_registration"] == 1
    assert [d.severity for d in result.diagnostics] == ["info"]


def test_a_decorator_nested_inside_a_function_is_rewritten_in_place() -> None:
    """v1 servers built inside `main()` register at the same nesting depth."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        def main():
            app = Server("demo")

            @app.set_logging_level()
            async def set_level(level) -> None:
                configure(level)

            return app
        """)
    result = transform(source)
    assert (
        '    app.add_request_handler("logging/setLevel", mcp_types.SetLevelRequestParams, _set_level_handler)'
        in result.code
    )
    assert "    async def _set_level_handler(" in result.code
    assert result.code.count("# mcp-codemod:") == 0


def test_a_stacked_decorator_blocks_the_rewrite_with_a_marker() -> None:
    """A second decorator changes what the module name binds, so the site is marked."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        app = Server("demo")

        @observed
        @app.list_tools()
        async def list_tools():
            return []
        """)
    result = transform(source)
    assert "@observed" in result.code
    assert "another decorator is stacked on it" in result.diagnostics[0].message
    assert "add_request_handler" in result.diagnostics[0].message


def test_an_attribute_receiver_blocks_the_rewrite_with_a_marker() -> None:
    """The emitted module-level adapter cannot close over `self`, so the site is marked."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        class Wrapper:
            def __init__(self):
                self.server = Server("demo")

                @self.server.list_tools()
                async def list_tools():
                    return []
        """)
    result = transform(source)
    assert "@self.server.list_tools()" in result.code
    assert "the server is reached through an attribute" in result.diagnostics[0].message


def test_a_wrong_arity_handler_blocks_the_rewrite_with_a_marker() -> None:
    """A handler signature that is not v1's old style is not guessed at."""
    source = textwrap.dedent("""\
        import mcp.types as types
        from mcp.server.lowlevel import Server

        app = Server("demo")

        @app.list_tools()
        async def list_tools(req: types.ListToolsRequest) -> types.ListToolsResult:
            return types.ListToolsResult(tools=[])
        """)
    result = transform(source)
    assert "the handler signature does not match the v1 form" in result.diagnostics[0].message


def test_a_sync_handler_blocks_the_rewrite_with_a_marker() -> None:
    """v1 lowlevel handlers were async; a sync def is not a shape the adapter can call."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        app = Server("demo")

        @app.list_tools()
        def list_tools():
            return []
        """)
    result = transform(source)
    assert "the handler is not `async def`" in result.diagnostics[0].message


def test_a_non_literal_decorator_argument_blocks_the_rewrite() -> None:
    """`@app.call_tool(validate_input=flag)` cannot be evaluated statically."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        app = Server("demo")

        @app.call_tool(validate_input=flag)
        async def call_tool(name, arguments):
            return []
        """)
    result = transform(source)
    assert "arguments the codemod cannot evaluate" in result.diagnostics[0].message


def test_a_taken_generated_name_blocks_the_rewrite() -> None:
    """The adapter's module-level name must not shadow existing user code."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        app = Server("demo")
        _list_tools_handler = object()

        @app.list_tools()
        async def list_tools():
            return []
        """)
    result = transform(source)
    assert "a generated name is already bound in this file" in result.diagnostics[0].message


def test_validate_input_false_omits_only_the_input_validation() -> None:
    """Only the input-validation block is dropped; v1 validated output regardless of the flag."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        app = Server("demo")

        @app.call_tool(validate_input=False)
        async def call_tool(name, arguments):
            return []
        """)
    result = transform(source)
    assert "instance=arguments" not in result.code
    assert "output_schema" in result.code
    assert "_app_tool_cache" in result.code


def test_adapter_imports_are_not_injected_when_already_bound() -> None:
    """A file that already imports `json` and `mcp_types` gets neither again."""
    source = textwrap.dedent("""\
        import json
        import mcp_types
        from mcp.server.lowlevel import Server

        app = Server("demo")

        @app.call_tool()
        async def call_tool(name, arguments):
            return [json.dumps(arguments)]
        """)
    result = transform(source)
    assert result.code.count("import json\n") == 1
    assert result.code.count("import mcp_types") == 1


def test_an_inline_timedelta_timeout_converts_to_seconds() -> None:
    """An inline `timedelta` timeout converts to seconds; on v2 the `timedelta` form fails on first request."""
    source = textwrap.dedent("""\
        from datetime import timedelta
        from mcp import ClientSession

        session = ClientSession(read, write, read_timeout_seconds=timedelta(seconds=5))
        """)
    result = transform(source)
    assert "read_timeout_seconds=timedelta(seconds=5).total_seconds()" in result.code
    assert [d.severity for d in result.diagnostics] == ["info"]


def test_a_positional_timeout_variable_is_marked_not_guessed() -> None:
    """A variable in v1's `timedelta` position cannot be proven convertible, so it gets a marker."""
    source = textwrap.dedent("""\
        from mcp import ClientSession

        session = ClientSession(read, write, timeout)
        """)
    result = transform(source)
    assert "session = ClientSession(read, write, timeout)" in result.code
    assert "pass this value's `.total_seconds()`" in result.diagnostics[0].message


def test_a_none_timeout_is_left_alone() -> None:
    """`None` is valid on both v1 and v2; nothing fires."""
    source = textwrap.dedent("""\
        from mcp import ClientSession

        session = ClientSession(read, write, None)
        """)
    result = transform(source)
    assert result.diagnostics == []


def test_a_cursor_keyword_on_an_annotated_session_wraps_into_params() -> None:
    """`cursor=` becomes the v2 `params=` form when the receiver is proven a `ClientSession`."""
    source = textwrap.dedent("""\
        from mcp import ClientSession

        async def load(session: ClientSession):
            return await session.list_tools(cursor=token)
        """)
    result = transform(source)
    assert "session.list_tools(params=mcp_types.PaginatedRequestParams(cursor=token))" in result.code
    assert "import mcp_types" in result.code


def test_a_url_wrapper_into_a_proven_session_read_is_unwrapped() -> None:
    """The `AnyUrl` wrapper is dropped when the receiver is a with-bound `ClientSession`."""
    source = textwrap.dedent("""\
        from pydantic import AnyUrl
        from mcp import ClientSession

        async def read(streams):
            async with ClientSession(streams[0], streams[1]) as session:
                return await session.read_resource(AnyUrl("demo://x"))
        """)
    result = transform(source)
    assert 'session.read_resource("demo://x")' in result.code


def test_a_url_wrapper_in_a_sdk_uri_keyword_is_unwrapped() -> None:
    """The wrapper is dropped on a callee that provably resolves into the SDK."""
    source = textwrap.dedent("""\
        import mcp.types as types
        from pydantic import AnyUrl

        resource = types.Resource(uri=AnyUrl(f"file://{path}"), name="n")
        """)
    result = transform(source)
    assert 'resource = types.Resource(uri=f"file://{path}", name="n")' in result.code


def test_a_url_wrapper_in_an_unproven_uri_keyword_is_marked() -> None:
    """On an unresolvable callee the value may still land in an mcp model, so mark rather than rewrite."""
    source = textwrap.dedent("""\
        import mcp
        from pydantic import AnyUrl

        notify(uri=AnyUrl("demo://x"), audience="all")
        """)
    result = transform(source)
    assert 'notify(uri=AnyUrl("demo://x"), audience="all")' in result.code
    assert "drop this URL wrapper" in result.diagnostics[0].message


def test_the_private_mcp_server_attribute_is_marked() -> None:
    """The marker names the v2 spelling of v1's widely-used private attribute."""
    source = textwrap.dedent("""\
        from mcp.server.mcpserver import MCPServer

        mcp = MCPServer("demo")
        server = mcp._mcp_server
        """)
    result = transform(source)
    assert "_lowlevel_server" in result.diagnostics[0].message


def test_the_handler_dicts_on_a_proven_lowlevel_server_are_marked() -> None:
    """Handler-dict introspection has no mechanical rewrite; the marker names the v2 lookup API."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        app = Server("demo")
        handler = app.request_handlers[CallToolRequest]
        """)
    result = transform(source)
    assert "get_request_handler(method)" in result.diagnostics[0].message


def test_a_class_body_handler_blocks_the_rewrite() -> None:
    """A decorated method in a class body cannot take a module-level adapter."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        app = Server("demo")

        class Handlers:
            @app.list_tools()
            async def list_tools(self):
                return []
        """)
    result = transform(source)
    assert "the handler is defined in a class body" in result.diagnostics[0].message


def test_a_decorator_argument_on_a_non_call_tool_kind_blocks_the_rewrite() -> None:
    """Only `call_tool` ever took a decorator argument on v1; anything else is not a known shape."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        app = Server("demo")

        @app.list_tools("extra")
        async def list_tools():
            return []
        """)
    result = transform(source)
    assert "arguments the codemod cannot evaluate" in result.diagnostics[0].message


def test_a_star_kwargs_handler_blocks_the_rewrite() -> None:
    """`**kwargs` hides the real signature, so the site is marked."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        app = Server("demo")

        @app.get_prompt()
        async def get_prompt(name, arguments, **kwargs):
            return None
        """)
    result = transform(source)
    assert "the handler signature does not match the v1 form" in result.diagnostics[0].message


def test_a_single_positional_argument_to_a_session_list_method_is_left_alone() -> None:
    """Only the exact v1 `cursor=` keyword form is wrapped."""
    source = textwrap.dedent("""\
        from mcp import ClientSession

        async def load(session: ClientSession):
            return await session.list_tools(token)
        """)
    result = transform(source)
    assert "session.list_tools(token)" in result.code
    assert result.diagnostics == []


def test_a_plain_string_uri_to_a_session_read_is_left_alone() -> None:
    """`session.read_resource("demo://x")` is already the v2 shape."""
    source = textwrap.dedent("""\
        from mcp import ClientSession

        async def read(session: ClientSession):
            return await session.read_resource("demo://x")
        """)
    result = transform(source)
    assert 'session.read_resource("demo://x")' in result.code
    assert result.diagnostics == []


def test_a_url_wrapper_in_a_file_without_sdk_imports_is_never_touched() -> None:
    """Without an SDK import the value cannot land in an mcp type; no marker, no rewrite."""
    source = textwrap.dedent("""\
        from pydantic import AnyUrl

        notify(uri=AnyUrl("demo://x"), audience="all")
        """)
    result = transform(source)
    assert result.code == source
    assert result.diagnostics == []


def test_constructing_a_union_alias_is_marked() -> None:
    """`JSONRPCMessage(...)` imports on v2 but is a plain union: calling it fails."""
    source = textwrap.dedent("""\
        from mcp.types import JSONRPCMessage

        message = JSONRPCMessage(payload)
        """)
    result = transform(source)
    assert "cannot be constructed" in result.diagnostics[0].message


def test_a_pydantic_method_on_a_union_alias_is_marked() -> None:
    """`JSONRPCMessage.model_validate_json(...)` has no pydantic methods on v2."""
    source = textwrap.dedent("""\
        import mcp.types as types

        message = types.JSONRPCMessage.model_validate_json(raw)
        """)
    result = transform(source)
    assert any("pydantic.TypeAdapter(JSONRPCMessage)" in d.message for d in result.diagnostics)


def test_a_str_annotated_uri_handler_gets_the_wire_string() -> None:
    """A handler declaring `uri: str` gets the wire string passed through, with no `AnyUrl` import."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        app = Server("demo")

        @app.read_resource()
        async def read_resource(uri: str) -> str:
            return uri
        """)
    result = transform(source)
    assert "await read_resource(params.uri)" in result.code
    assert "AnyUrl" not in result.code


def test_an_unannotated_uri_handler_keeps_v1_anyurl_parity() -> None:
    """Without a `str` annotation the adapter passes `AnyUrl(params.uri)`, exactly what v1 passed."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        app = Server("demo")

        @app.subscribe_resource()
        async def subscribe(uri):
            record(uri)
        """)
    result = transform(source)
    assert "await subscribe(AnyUrl(params.uri))" in result.code
    assert "from pydantic import AnyUrl" in result.code


def test_a_model_method_on_a_non_alias_receiver_is_not_marked() -> None:
    """`model_validate` on a concrete model (or anything else) is live v2 API."""
    source = textwrap.dedent("""\
        from mcp.types import Tool

        tool = Tool.model_validate(payload)
        own = config.model_dump()
        """)
    result = transform(source)
    assert not any(d.transform == "union_alias" for d in result.diagnostics)


def test_imports_inject_at_the_top_even_with_a_late_import() -> None:
    """A mid-file import must not anchor injection below the registration code."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        app = Server("demo")

        @app.list_tools()
        async def list_tools():
            return []

        import late_helper
        """)
    result = transform(source)
    lines = result.code.splitlines()
    assert lines.index("import mcp_types") < lines.index('app = Server("demo")')


def test_a_docstring_and_future_import_stay_first() -> None:
    """Injected imports respect the docstring and `__future__` position rules."""
    source = textwrap.dedent('''\
        """Module docs."""

        from __future__ import annotations
        from mcp.server.lowlevel import Server

        app = Server("demo")

        @app.get_prompt()
        async def get_prompt(name, arguments):
            return None
        ''')
    result = transform(source)
    lines = result.code.splitlines()
    assert lines[0] == '"""Module docs."""'
    assert lines.index("from __future__ import annotations") < lines.index("import mcp_types")


def test_a_conditional_import_does_not_suppress_injection() -> None:
    """A TYPE_CHECKING-gated import does not bind at runtime, so the adapter's
    import is still injected at module level."""
    source = textwrap.dedent("""\
        from typing import TYPE_CHECKING
        from mcp.server.lowlevel import Server

        if TYPE_CHECKING:
            from collections.abc import Iterable

        app = Server("demo")

        @app.call_tool()
        async def call_tool(name, arguments):
            return []
        """)
    result = transform(source)
    top_level = [line for line in result.code.splitlines() if line.startswith("from collections.abc")]
    assert top_level == ["from collections.abc import Iterable"]


def test_a_module_binding_of_an_adapter_import_name_blocks_the_rewrite() -> None:
    """`json = None` at module level would shadow the injected import inside the
    adapter, so the site is marked instead of silently broken."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        json = None
        app = Server("demo")

        @app.call_tool()
        async def call_tool(name, arguments):
            return []
        """)
    result = transform(source)
    assert "a name the generated adapter needs is already bound" in result.diagnostics[0].message


def test_a_handler_named_like_a_template_local_blocks_the_rewrite() -> None:
    """A handler called `completion` would be shadowed by the adapter's own local."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        app = Server("demo")

        @app.completion()
        async def completion(ref, argument, context):
            return None
        """)
    result = transform(source)
    assert "collides with a name the generated adapter uses" in result.diagnostics[0].message


def test_a_blocked_progress_site_names_the_notification_api() -> None:
    """Progress is a notification; the guidance must not send users to the
    request-handler API where the handler would never fire."""
    source = textwrap.dedent("""\
        from mcp.server.lowlevel import Server

        app = Server("demo")

        @app.progress_notification()
        def on_progress(token, progress, total, message):
            pass
        """)
    result = transform(source)
    assert "add_notification_handler" in result.diagnostics[0].message


def test_a_list_handler_returning_the_full_result_passes_through() -> None:
    """v1's wrapper isinstance-passed a returned result model through; the adapter
    must not double-wrap it."""
    source = textwrap.dedent("""\
        import mcp.types as types
        from mcp.server.lowlevel import Server

        app = Server("demo")

        @app.list_tools()
        async def list_tools():
            return types.ListToolsResult(tools=[])
        """)
    result = transform(source)
    assert "if isinstance(result, mcp_types.ListToolsResult):" in result.code
    assert "return result" in result.code


def test_the_timeout_rewrite_is_idempotent_and_floats_are_untouched() -> None:
    """A second run over `.total_seconds()` output and a plain float timeout both
    produce nothing -- no rewrite, no marker."""
    source = textwrap.dedent("""\
        from datetime import timedelta
        from mcp import ClientSession

        a = ClientSession(read, write, read_timeout_seconds=timedelta(seconds=5))
        b = ClientSession(read, write, 30.0)
        """)
    once = transform(source)
    assert "timedelta(seconds=5).total_seconds()" in once.code
    assert not any(d.severity == "manual" for d in once.diagnostics)
    again = transform(once.code)
    assert again.code == once.code
    assert again.diagnostics == []


def test_no_injection_happens_when_everything_needed_is_bound() -> None:
    """A rewrite that needs only `mcp_types` injects nothing into a file that
    already imports it."""
    source = textwrap.dedent("""\
        import mcp_types
        from mcp import ClientSession

        async def load(session: ClientSession):
            return await session.list_tools(cursor=token)
        """)
    result = transform(source)
    assert result.code.count("import mcp_types") == 1
