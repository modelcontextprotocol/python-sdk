"""Expose two filesystem roots and verify the server's tool can read them back."""

from pydantic import FileUrl

from mcp.client import Client, ClientRequestContext
from mcp.types import ListRootsResult, Root, TextContent
from stories._harness import Target, run_client


async def list_roots(context: ClientRequestContext) -> ListRootsResult:
    return ListRootsResult(
        roots=[
            Root(uri=FileUrl("file:///workspace/project"), name="project"),
            Root(uri=FileUrl("file:///workspace/scratch")),
        ]
    )


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode, list_roots_callback=list_roots) as client:
        result = await client.call_tool("show_roots", {})

        assert not result.is_error, result
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == ("file:///workspace/project (project)\nfile:///workspace/scratch (unnamed)"), (
            result.content[0].text
        )


if __name__ == "__main__":
    run_client(main)
