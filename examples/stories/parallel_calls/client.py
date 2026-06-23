"""Issue concurrent `call_tool` requests on one `Client`; assert per-call progress demux."""

import anyio

from mcp.client import Client
from mcp.types import TextContent
from stories._harness import connect_from_args, run_client


async def scenario(client: Client) -> None:
    party = ["a", "b"]
    results: dict[str, str] = {}
    received: dict[str, list[str | None]] = {tag: [] for tag in party}

    def collector(tag: str):
        async def on_progress(progress: float, total: float | None, message: str | None) -> None:
            received[tag].append(message)

        return on_progress

    async def call(tag: str) -> None:
        result = await client.call_tool("meet", {"tag": tag, "party": party}, progress_callback=collector(tag))
        assert not result.is_error, result
        assert isinstance(result.content[0], TextContent)
        results[tag] = result.content[0].text

    # Neither call can return until both handlers are running concurrently; a server that
    # processed requests one-at-a-time would never set the second event and we'd time out here.
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(call, "a")
            tg.start_soon(call, "b")

    assert results == {"a": "a", "b": "b"}, results
    # Progress is token-keyed per request: each callback saw only its own tag, never the sibling's.
    assert received == {"a": ["a"], "b": ["b"]}, received


if __name__ == "__main__":
    run_client(scenario, connect=connect_from_args(__file__))
