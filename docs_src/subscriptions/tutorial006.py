from mcp_types import INVALID_REQUEST, SubscriptionsListenRequestParams

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError

# Who may see each file. Replace this table with a database or your RBAC system.
ACCESS = {
    "files://report.pdf": {"alice", "bob"},
    "files://payroll.csv": {"carol"},
}


def can_access(user: str | None, uri: str) -> bool:
    return user is not None and user in ACCESS.get(uri, set())


async def gate_subscriptions(ctx: ServerRequestContext, call_next: CallNext) -> HandlerResult:
    if ctx.method == "subscriptions/listen":
        params = SubscriptionsListenRequestParams.model_validate(ctx.params or {}, by_name=False)
        token = get_access_token()
        user = token.subject if token else None
        if not all(can_access(user, uri) for uri in params.notifications.resource_subscriptions or ()):
            raise MCPError(INVALID_REQUEST, "not permitted to watch the requested resources")
    return await call_next(ctx)


mcp = MCPServer("Reports", middleware=[gate_subscriptions])


@mcp.resource("files://{name}")
def file(name: str) -> str:
    uri = f"files://{name}"
    token = get_access_token()
    if not can_access(token.subject if token else None, uri):
        raise MCPError(INVALID_REQUEST, f"Unknown resource: {uri}")
    return f"contents of {name}"
