"""Asserts each variant publishes a `who` object schema and the call round-trips."""

from mcp.client import Client
from mcp.types import TextContent
from stories._harness import Target, run_client


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode) as client:
        listed = await client.list_tools()
        by_name = {t.name: t for t in listed.tools}
        assert set(by_name) == {"greet_pydantic", "greet_typeddict", "greet_dataclass", "greet_dict"}

        for name in ("greet_pydantic", "greet_typeddict", "greet_dataclass"):
            schema = by_name[name].input_schema
            assert schema["required"] == ["who"], schema
            # MCPServer emits a $defs/$ref pair; lowlevel inlines. Resolve either.
            who = schema["properties"]["who"]
            if "$ref" in who:
                who = schema["$defs"][who["$ref"].rsplit("/", 1)[-1]]
            assert "name" in who["properties"], who

            result = await client.call_tool(name, {"who": {"name": "Ada", "title": "colleague"}})
            assert not result.is_error, result
            assert isinstance(result.content[0], TextContent)
            assert result.content[0].text == "Hello Ada, my colleague"

        # dict[str, Any] → free-form object schema, no nested `properties` required.
        dict_who = by_name["greet_dict"].input_schema["properties"]["who"]
        assert dict_who["type"] == "object" and "$ref" not in dict_who
        result = await client.call_tool("greet_dict", {"who": {"name": "Ada"}})
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Hello Ada, my friend"


if __name__ == "__main__":
    run_client(main)
