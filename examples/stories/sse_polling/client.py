"""Call a tool whose SSE stream the server closes mid-flight; the call still completes. HTTP-only — no SSE on stdio."""

import anyio
from mcp_types import TextContent

from mcp.client import Client
from stories._harness import Target, run_client


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode) as client:
        messages: list[str | None] = []

        async def on_progress(progress: float, total: float | None, message: str | None) -> None:
            messages.append(message)

        with anyio.fail_after(10):
            result = await client.call_tool("long_operation", {}, progress_callback=on_progress)

        # The transport survived the server's close: it reconnected with Last-Event-ID and got the replayed response.
        assert not result.is_error, result
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "resumed"

        # "after-close" was emitted while no SSE stream was open — proof the event store buffered it for the replay.
        assert messages == ["before-close", "after-close"], messages


if __name__ == "__main__":
    run_client(main)
