"""Expose two filesystem roots and verify the server's tool can read them back."""

from typing import Any

from pydantic import FileUrl

from mcp.client import Client, ClientRequestContext
from mcp.types import ListRootsResult, Root, TextContent
from stories._harness import connect_from_args, run_client


async def list_roots(context: ClientRequestContext) -> ListRootsResult:
    return ListRootsResult(
        roots=[
            Root(uri=FileUrl("file:///workspace/project"), name="project"),
            Root(uri=FileUrl("file:///workspace/scratch")),
        ]
    )


def client_kw() -> dict[str, Any]:
    return {"list_roots_callback": list_roots}


async def scenario(client: Client) -> None:
    result = await client.call_tool("show_roots", {})

    assert not result.is_error, result
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == ("file:///workspace/project (project)\nfile:///workspace/scratch (unnamed)"), (
        result.content[0].text
    )


if __name__ == "__main__":
    run_client(scenario, connect=connect_from_args(__file__), **client_kw())
