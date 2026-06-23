"""Supply a canned sampling_callback and assert its text round-trips through the tool."""

from typing import Any

from mcp.client import Client, ClientRequestContext
from mcp.types import CreateMessageRequestParams, CreateMessageResult, TextContent
from stories._harness import connect_from_args, run_client


async def sampling_callback(context: ClientRequestContext, params: CreateMessageRequestParams) -> CreateMessageResult:
    # A real host would call its LLM provider here; the example returns a deterministic
    # canned answer so the round-trip is assertable.
    return CreateMessageResult(
        role="assistant",
        content=TextContent(text="[canned summary]"),
        model="stub-model",
        stop_reason="endTurn",
    )


def client_kw() -> dict[str, Any]:
    return {"sampling_callback": sampling_callback}


async def scenario(client: Client) -> None:
    result = await client.call_tool("summarize", {"text": "hello world"})

    assert not result.is_error, result
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "[canned summary]", result.content[0].text


if __name__ == "__main__":
    run_client(scenario, connect=connect_from_args(__file__), **client_kw())
