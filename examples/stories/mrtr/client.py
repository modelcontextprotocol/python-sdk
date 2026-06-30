"""Drive the deploy tool both ways: the Client auto-loop, and a manual session-level loop."""

import mcp_types as types

from mcp import MCPError
from mcp.client import Client, ClientRequestContext
from stories._harness import Target, run_client


async def on_elicit(context: ClientRequestContext, params: types.ElicitRequestParams) -> types.ElicitResult:
    # The same callback serves legacy push-style elicitation/create requests AND embedded
    # InputRequiredResult.input_requests entries — the driver dispatches both here.
    assert isinstance(params, types.ElicitRequestFormParams)
    assert "confirm" in params.requested_schema["properties"]
    return types.ElicitResult(action="accept", content={"confirm": True})


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode, elicitation_callback=on_elicit) as client:
        # ── auto-loop: Client.call_tool dispatches input_requests to on_elicit and retries
        # internally; the caller just sees the final CallToolResult.
        deployed = await client.call_tool("deploy", {"env": "production"})
        assert isinstance(deployed.content[0], types.TextContent)
        assert deployed.content[0].text == "deployed to production", deployed

        # ── manual loop: drop to client.session for the raw InputRequiredResult so the
        # request_state can be persisted between rounds (e.g. across a process restart).
        first = await client.session.call_tool("deploy", {"env": "staging"}, allow_input_required=True)
        assert isinstance(first, types.InputRequiredResult)
        assert first.input_requests is not None and "confirm" in first.input_requests
        # The wire request_state is OPAQUE: server.py wrote "awaiting-confirm", but the
        # boundary middleware sealed it before it left the server — the plaintext never
        # crosses the wire, and the client just echoes the token byte-exact.
        token = first.request_state
        assert token is not None and token != "awaiting-confirm", token

        responses: types.InputResponses = {"confirm": types.ElicitResult(action="decline")}

        # Tamper demonstration: flip one character and retry. The token decodes strictly
        # canonically, so changing ANY character — including the final one — rejects.
        # Every verification failure collapses to ONE frozen wire error; the real reason
        # (here: a failed authentication tag) appears only in the server's log.
        i = len(token) // 2
        tampered = token[:i] + ("A" if token[i] != "A" else "B") + token[i + 1 :]
        try:
            await client.session.call_tool(
                "deploy",
                {"env": "staging"},
                input_responses=responses,
                request_state=tampered,
                allow_input_required=True,
            )
        except MCPError as e:
            assert e.code == types.INVALID_PARAMS
            assert e.message == "Invalid or expired requestState"
            assert e.data == {"reason": "invalid_request_state"}
        else:
            raise AssertionError("expected MCPError for a tampered requestState")

        # The untampered token still completes the round. Decline this time so the path
        # diverges from the auto-loop run above.
        second = await client.session.call_tool(
            "deploy",
            {"env": "staging"},
            input_responses=responses,
            request_state=token,
            allow_input_required=True,
        )
        assert isinstance(second, types.CallToolResult)
        assert isinstance(second.content[0], types.TextContent)
        assert second.content[0].text == "deployment to staging cancelled", second


if __name__ == "__main__":
    run_client(main)
