from mcp import ClientSession, types
from mcp.shared.context import RequestContext


async def handle_list_roots(
    context: RequestContext[ClientSession, None],
) -> types.ListRootsResult:
    """Return the client's workspace roots."""
    return types.ListRootsResult(
        roots=[
            types.Root(uri="file:///home/user/project", name="My Project"),
            types.Root(uri="file:///home/user/data", name="Data Folder"),
        ]
    )


# Pass the callback when creating the session
session = ClientSession(
    read_stream,
    write_stream,
    list_roots_callback=handle_list_roots,
)
