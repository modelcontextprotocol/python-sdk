"""Two concurrent `Client`s, so `main` takes `targets`; their rendezvous in one tool proves concurrent dispatch."""

import anyio
from mcp_types import TextContent

from mcp.client import Client
from stories._harness import TargetFactory, run_client


async def main(targets: TargetFactory, *, mode: str = "auto") -> None:
    party = ["a", "b"]
    results: dict[str, str] = {}
    received: dict[str, list[str | None]] = {tag: [] for tag in party}

    async def attend(tag: str) -> None:
        async def on_progress(progress: float, total: float | None, message: str | None) -> None:
            received[tag].append(message)

        # Each targets() call is a fresh connection to the SAME server, so the two `meet` handlers can rendezvous.
        async with Client(targets(), mode=mode) as client:
            result = await client.call_tool("meet", {"tag": tag, "party": party}, progress_callback=on_progress)
            assert not result.is_error, result
            assert isinstance(result.content[0], TextContent)
            results[tag] = result.content[0].text

    # Neither call returns until both handlers run concurrently — a serial server would never set the second event.
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(attend, "a")
            tg.start_soon(attend, "b")

    assert results == {"a": "a", "b": "b"}, results
    # Progress is routed by progress token: each callback saw only its own tag, never the sibling's.
    assert received == {"a": ["a"], "b": ["b"]}, received


if __name__ == "__main__":
    run_client(main)
