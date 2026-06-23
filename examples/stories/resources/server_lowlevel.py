"""Resources primitive (lowlevel API): hand-built list/templates/read handlers."""

from typing import Any

from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.shared.exceptions import MCPError
from mcp.types.jsonrpc import INVALID_PARAMS
from stories._hosting import run_server_from_args


def build_server() -> Server[Any]:
    async def list_resources(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(
            resources=[
                types.Resource(
                    uri="config://app",
                    name="app_config",
                    description="Static application config.",
                    mime_type="application/json",
                )
            ]
        )

    async def list_resource_templates(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListResourceTemplatesResult:
        return types.ListResourceTemplatesResult(
            resource_templates=[
                types.ResourceTemplate(
                    uri_template="greeting://{name}",
                    name="greeting",
                    description="A greeting for the named subject.",
                    mime_type="text/plain",
                )
            ]
        )

    async def read_resource(
        ctx: ServerRequestContext[Any], params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        if params.uri == "config://app":
            text, mime = '{"feature": true}', "application/json"
        elif params.uri.startswith("greeting://"):
            text, mime = f"Hello, {params.uri.removeprefix('greeting://')}!", "text/plain"
        else:
            raise MCPError(code=INVALID_PARAMS, message=f"Resource not found: {params.uri}")
        return types.ReadResourceResult(
            contents=[types.TextResourceContents(uri=params.uri, mime_type=mime, text=text)]
        )

    return Server(
        "resources-example",
        on_list_resources=list_resources,
        on_list_resource_templates=list_resource_templates,
        on_read_resource=read_resource,
    )


if __name__ == "__main__":
    run_server_from_args(build_server)
