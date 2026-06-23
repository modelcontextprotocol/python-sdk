"""Auto-answer form and URL elicitations and assert the tool result reflects them."""

from typing import Any

from mcp import types
from mcp.client import Client, ClientRequestContext
from stories._harness import connect_from_args, run_client


async def on_elicit(context: ClientRequestContext, params: types.ElicitRequestParams) -> types.ElicitResult:
    if isinstance(params, types.ElicitRequestURLParams):
        # A real client would open params.url in a browser, then wait for the matching
        # notifications/elicitation/complete before resolving.
        assert params.url.startswith("https://example.com/")
        return types.ElicitResult(action="accept")
    assert "username" in params.requested_schema["properties"]
    return types.ElicitResult(action="accept", content={"username": "alice", "plan": "pro"})


client_kw: dict[str, Any] = {"elicitation_callback": on_elicit}


async def scenario(client: Client) -> None:
    registered = await client.call_tool("register_user", {})
    assert isinstance(registered.content[0], types.TextContent)
    assert registered.content[0].text == "registered alice (plan: pro)", registered

    linked = await client.call_tool("link_account", {"provider": "github"})
    assert isinstance(linked.content[0], types.TextContent)
    assert linked.content[0].text == "linked github", linked


if __name__ == "__main__":
    run_client(scenario, connect=connect_from_args(__file__), **client_kw)
