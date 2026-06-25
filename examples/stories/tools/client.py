"""List tools, inspect schemas + annotations, call both tools, assert structured output."""

from mcp.client import Client
from mcp.types import TextContent
from stories._harness import Target, run_client


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode) as client:
        listed = await client.list_tools()
        by_name = {t.name: t for t in listed.tools}
        assert set(by_name) == {"calc", "echo"}

        calc = by_name["calc"]
        assert calc.annotations is not None and calc.annotations.read_only_hint is True
        assert calc.annotations.idempotent_hint is True
        assert calc.output_schema is not None
        assert set(calc.input_schema.get("required", ())) >= {"op", "a", "b"}
        assert by_name["echo"].output_schema is None

        result = await client.call_tool("calc", {"op": "add", "a": 2, "b": 3})
        assert not result.is_error
        assert result.structured_content == {"op": "add", "result": 5.0}, result

        echoed = await client.call_tool("echo", {"text": "hi"})
        assert echoed.structured_content is None
        assert isinstance(echoed.content[0], TextContent) and echoed.content[0].text == "hi"


if __name__ == "__main__":
    run_client(main)
