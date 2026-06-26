from mcp_types import CallToolResult, ElicitRequest, ElicitResult, InputRequest, InputRequiredResult, InputResponse

from mcp import Client


def fulfil(request: InputRequest) -> InputResponse:
    if not isinstance(request, ElicitRequest):
        raise NotImplementedError(f"this client cannot answer a {request.method!r} request")
    return ElicitResult(action="accept", content={"region": "eu-west-1"})


async def provision(client: Client, name: str) -> CallToolResult:
    result = await client.session.call_tool("provision", {"name": name}, allow_input_required=True)
    while isinstance(result, InputRequiredResult):
        responses = {key: fulfil(request) for key, request in (result.input_requests or {}).items()}
        result = await client.session.call_tool(
            "provision",
            {"name": name},
            input_responses=responses,
            request_state=result.request_state,
            allow_input_required=True,
        )
    return result
