from pydantic import FileUrl

from mcp.client import ClientRequestContext
from mcp.types import CreateMessageRequestParams, CreateMessageResult, ListRootsResult, Root, TextContent


async def handle_sampling(
    context: ClientRequestContext,
    params: CreateMessageRequestParams,
) -> CreateMessageResult:
    return CreateMessageResult(
        role="assistant",
        content=TextContent(type="text", text="The answer is 42."),
        model="my-llm",
    )


async def handle_list_roots(context: ClientRequestContext) -> ListRootsResult:
    return ListRootsResult(roots=[Root(uri=FileUrl("file:///home/ada/notebooks"), name="notebooks")])
