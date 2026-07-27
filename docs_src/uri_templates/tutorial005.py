from mcp_types import (
    ListResourceTemplatesResult,
    PaginatedRequestParams,
    ReadResourceRequestParams,
    ReadResourceResult,
    ResourceTemplate,
    TextResourceContents,
)

from mcp.server import Server, ServerRequestContext
from mcp.shared.path_security import contains_path_traversal, is_absolute_path
from mcp.shared.uri_template import UriTemplate

TEMPLATES = {
    "manuals": UriTemplate.parse("manuals://{+path}"),
    "books": UriTemplate.parse("books://{isbn}"),
}

MANUALS = {"printing/setup.md": "# Printer setup", "returns.md": "# Returns policy"}
BOOKS = {"978-0441172719": "Dune by Frank Herbert"}


def read_manual_safely(path: str) -> str:
    if contains_path_traversal(path) or is_absolute_path(path):
        raise ValueError("rejected")
    return MANUALS[path]


async def read_resource(ctx: ServerRequestContext, params: ReadResourceRequestParams) -> ReadResourceResult:
    if (matched := TEMPLATES["manuals"].match(params.uri)) is not None:
        text = read_manual_safely(str(matched["path"]))
        return ReadResourceResult(contents=[TextResourceContents(uri=params.uri, text=text)])

    if (matched := TEMPLATES["books"].match(params.uri)) is not None:
        text = BOOKS[str(matched["isbn"])]
        return ReadResourceResult(contents=[TextResourceContents(uri=params.uri, text=text)])

    raise ValueError(f"Unknown resource: {params.uri}")


async def list_resource_templates(
    ctx: ServerRequestContext, params: PaginatedRequestParams | None
) -> ListResourceTemplatesResult:
    return ListResourceTemplatesResult(
        resource_templates=[
            ResourceTemplate(name=name, uri_template=str(template)) for name, template in TEMPLATES.items()
        ]
    )


server = Server(
    "Bookshop",
    on_read_resource=read_resource,
    on_list_resource_templates=list_resource_templates,
)
