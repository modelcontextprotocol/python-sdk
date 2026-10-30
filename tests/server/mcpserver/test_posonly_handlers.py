import anyio
import pytest
from mcp.client.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.shared._callable_inspection import split_positional_args


def test_split_positional_args():
    # 1. Pure positional-only
    def f1(x: str, /):
        return x

    args, kwargs = split_positional_args(f1, {"x": "hello"})
    assert args == ("hello",)
    assert kwargs == {}

    # 2. Positional-only with defaults
    def f2(x: int, y: str = "default_y", /):
        return x, y

    # Default not overridden
    args, kwargs = split_positional_args(f2, {"x": 42})
    assert args == (42,)
    assert kwargs == {}

    # Default overridden
    args, kwargs = split_positional_args(f2, {"x": 42, "y": "custom"})
    assert args == (42, "custom")
    assert kwargs == {}

    # 3. Mixed positional-only, regular, and kw-only
    def f3(a: str, /, b: int, *, c: bool = True):
        return a, b, c

    args, kwargs = split_positional_args(f3, {"a": "pos", "b": 10, "c": False})
    assert args == ("pos",)
    assert kwargs == {"b": 10, "c": False}

    # 4. No positional-only parameters
    def f4(a: str, b: int = 1):
        return a, b

    args, kwargs = split_positional_args(f4, {"a": "val", "b": 2})
    assert args == ()
    assert kwargs == {"a": "val", "b": 2}

    # 5. Method
    class Greeter:
        def greet(self, msg: str, /):
            return f"hi {msg}"

    g = Greeter()
    args, kwargs = split_positional_args(g.greet, {"msg": "there"})
    assert args == ("there",)
    assert kwargs == {}


@pytest.mark.anyio
async def test_mcpserver_posonly_tools_prompts_resources():
    mcp = MCPServer("test_posonly")

    @mcp.tool()
    def sync_tool(msg: str, /) -> str:
        return f"sync:{msg}"

    @mcp.tool()
    async def async_tool(msg: str, /) -> str:
        return f"async:{msg}"

    @mcp.tool()
    def mixed_tool(x: int, /, y: str = "world") -> str:
        return f"{x}:{y}"

    @mcp.prompt()
    def sync_prompt(name: str, /) -> str:
        return f"hello {name}"

    @mcp.prompt()
    async def async_prompt(name: str, /) -> str:
        return f"async hello {name}"

    @mcp.resource("test://{item}")
    def sync_res(item: str, /) -> str:
        return f"content:{item}"

    @mcp.resource("async://{item}")
    async def async_res(item: str, /) -> str:
        return f"async_content:{item}"

    async with Client(mcp) as client:
        # Tool tests
        t1 = await client.call_tool("sync_tool", {"msg": "apple"})
        assert not t1.is_error
        assert t1.content[0].text == "sync:apple"

        t2 = await client.call_tool("async_tool", {"msg": "banana"})
        assert not t2.is_error
        assert t2.content[0].text == "async:banana"

        t3 = await client.call_tool("mixed_tool", {"x": 7, "y": "universe"})
        assert not t3.is_error
        assert t3.content[0].text == "7:universe"

        t3_default = await client.call_tool("mixed_tool", {"x": 9})
        assert not t3_default.is_error
        assert t3_default.content[0].text == "9:world"

        # Prompt tests
        p1 = await client.get_prompt("sync_prompt", {"name": "carol"})
        assert p1.messages[0].content.text == "hello carol"

        p2 = await client.get_prompt("async_prompt", {"name": "dave"})
        assert p2.messages[0].content.text == "async hello dave"

        # Resource tests
        r1 = await client.read_resource("test://gadget")
        assert r1.contents[0].text == "content:gadget"

        r2 = await client.read_resource("async://widget")
        assert r2.contents[0].text == "async_content:widget"
