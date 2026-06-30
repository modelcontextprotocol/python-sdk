"""Multi-round tool result (2026 era): a tool returns input_required and resumes from echoed state."""

from mcp_types import ElicitRequest, ElicitRequestedSchema, ElicitRequestFormParams, ElicitResult, InputRequiredResult

from mcp.server.mcpserver import Context, MCPServer, RequestStateSecurity
from stories._hosting import run_server_from_args

CONFIRM_SCHEMA: ElicitRequestedSchema = {
    "type": "object",
    "properties": {"confirm": {"type": "boolean", "description": "Proceed with the deployment?"}},
    "required": ["confirm"],
}


def build_server() -> MCPServer:
    # requestState round-trips through the client, so the SDK requires a protection
    # policy before it lets a tool mint one. ephemeral() = a key generated at process
    # start; right for single-process servers like this one. Fleets share keys=[...].
    mcp = MCPServer("mrtr-example", request_state_security=RequestStateSecurity.ephemeral())

    @mcp.tool(description="Deploy to an environment, asking the user to confirm first.")
    async def deploy(env: str, ctx: Context) -> str | InputRequiredResult:
        responses = ctx.input_responses
        if responses is None or "confirm" not in responses:
            # First round: ask the client to elicit confirmation. The handler writes its
            # request_state in PLAINTEXT — the boundary middleware seals it into an opaque
            # token on the way out and unseals the echo on the retry, so this code never
            # touches the crypto. (client.py proves the wire never carries this string.)
            ask = ElicitRequest(
                params=ElicitRequestFormParams(message=f"Deploy to {env}?", requested_schema=CONFIRM_SCHEMA)
            )
            return InputRequiredResult(input_requests={"confirm": ask}, request_state="awaiting-confirm")
        # Retry round: the client echoed the sealed token byte-exact; the boundary
        # verified it and handed back the plaintext this handler originally wrote.
        assert ctx.request_state == "awaiting-confirm", ctx.request_state
        answer = responses["confirm"]
        if isinstance(answer, ElicitResult) and answer.action == "accept" and (answer.content or {}).get("confirm"):
            return f"deployed to {env}"
        return f"deployment to {env} cancelled"

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
