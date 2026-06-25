"""Auto-answer form and URL elicitations and assert the tool result reflects them."""

from mcp import types
from mcp.client import Client, ClientRequestContext
from stories._harness import Target, run_client


async def on_elicit(context: ClientRequestContext, params: types.ElicitRequestParams) -> types.ElicitResult:
    if isinstance(params, types.ElicitRequestURLParams):
        # A real client would ask consent and open params.url in a browser, returning
        # `accept` right away; the server's notifications/elicitation/complete arrives
        # afterward (once the out-of-band flow finishes) for the client to correlate.
        assert params.url.startswith("https://example.com/")
        return types.ElicitResult(action="accept")
    assert "username" in params.requested_schema["properties"]
    return types.ElicitResult(action="accept", content={"username": "alice", "plan": "pro"})


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode, elicitation_callback=on_elicit) as client:
        registered = await client.call_tool("register_user", {})
        assert isinstance(registered.content[0], types.TextContent)
        assert registered.content[0].text == "registered alice (plan: pro)", registered

        linked = await client.call_tool("link_account", {"provider": "github"})
        assert isinstance(linked.content[0], types.TextContent)
        assert linked.content[0].text == "linked github", linked


if __name__ == "__main__":
    run_client(main)
