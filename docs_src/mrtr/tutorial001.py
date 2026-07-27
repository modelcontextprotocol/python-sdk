from mcp_types import (
    CallToolRequestParams,
    CallToolResult,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

from mcp.server import Server, ServerRequestContext

ASK_REGION = ElicitRequest(
    params=ElicitRequestFormParams(
        message="Which region should the database live in?",
        requested_schema={
            "type": "object",
            "properties": {"region": {"type": "string"}},
            "required": ["region"],
        },
    )
)


async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(
        tools=[
            Tool(
                name="provision",
                description="Provision a database. Asks which region to put it in.",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            )
        ]
    )


async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult | InputRequiredResult:
    answer = (params.input_responses or {}).get("region")
    if not isinstance(answer, ElicitResult) or answer.content is None:
        return InputRequiredResult(input_requests={"region": ASK_REGION}, request_state="provision-v1")
    name = (params.arguments or {})["name"]
    text = f"Provisioned {name!r} in {answer.content['region']}."
    return CallToolResult(content=[TextContent(type="text", text=text)])


server = Server("Provisioner", on_list_tools=list_tools, on_call_tool=call_tool)
