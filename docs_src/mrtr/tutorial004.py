from mcp_types import ElicitRequest, ElicitRequestFormParams, ElicitResult, InputRequiredResult

from mcp.server.mcpserver import Context, MCPServer, RequestStateSecurity
from mcp.server.mcpserver.prompts.base import UserMessage

mcp = MCPServer("Briefing", request_state_security=RequestStateSecurity.ephemeral())

ASK_AUDIENCE = ElicitRequest(
    params=ElicitRequestFormParams(
        message="Who is the briefing for?",
        requested_schema={
            "type": "object",
            "properties": {"audience": {"type": "string"}},
            "required": ["audience"],
        },
    )
)


@mcp.prompt()
async def briefing(ctx: Context) -> list[UserMessage] | InputRequiredResult:
    """Draft a briefing tuned to its audience."""
    answer = (ctx.input_responses or {}).get("audience")
    if not isinstance(answer, ElicitResult) or answer.content is None:
        return InputRequiredResult(input_requests={"audience": ASK_AUDIENCE})
    return [UserMessage(f"Write a briefing for {answer.content['audience']}.")]
