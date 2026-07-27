"""Supply a canned sampling_callback and assert its text round-trips through the tool."""

from mcp_types import CreateMessageRequestParams, CreateMessageResult, TextContent

from mcp.client import Client, ClientRequestContext
from stories._harness import Target, run_client


async def on_sample(context: ClientRequestContext, params: CreateMessageRequestParams) -> CreateMessageResult:
    # A real host would call its LLM provider here; the example returns a deterministic
    # canned answer so the round-trip is assertable.
    return CreateMessageResult(
        role="assistant",
        content=TextContent(text="[canned summary]"),
        model="stub-model",
        stop_reason="endTurn",
    )


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode, sampling_callback=on_sample) as client:
        result = await client.call_tool("summarize", {"text": "hello world"})

        assert not result.is_error, result
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "[canned summary]", result.content[0].text


if __name__ == "__main__":
    run_client(main)
