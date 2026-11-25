from mcp.server import Server, ServerRequestContext
from mcp.types import (
    ListResourcesResult,
    PaginatedRequestParams,
    ReadResourceRequestParams,
    ReadResourceResult,
    Resource,
    TextResourceContents,
)

RESOURCES = {
    "config://shop": '{"currency": "USD", "tax_rate": 0.08}',
    "status://health": "ok",
}


async def list_resources(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListResourcesResult:
    return ListResourcesResult(resources=[Resource(name=uri, uri=uri) for uri in RESOURCES])


async def read_resource(ctx: ServerRequestContext, params: ReadResourceRequestParams) -> ReadResourceResult:
    if (text := RESOURCES.get(params.uri)) is not None:
        return ReadResourceResult(contents=[TextResourceContents(uri=params.uri, text=text)])
    raise ValueError(f"Unknown resource: {params.uri}")


server = Server("Bookshop", on_list_resources=list_resources, on_read_resource=read_resource)
