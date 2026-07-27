from mcp.server.apps import Apps, ResourceCsp, ResourcePermissions
from mcp.server.mcpserver import MCPServer

DASHBOARD_HTML = "<!doctype html><title>Dashboard</title><canvas id='chart'></canvas>"

apps = Apps()


@apps.tool(resource_uri="ui://dashboard/app.html", visibility=["app"])
def refresh_dashboard() -> str:
    """Refresh the dashboard data."""
    return "refreshed"


apps.add_html_resource(
    "ui://dashboard/app.html",
    DASHBOARD_HTML,
    title="Dashboard",
    csp=ResourceCsp(connect_domains=["https://api.example.com"]),
    permissions=ResourcePermissions(clipboard_write={}),
    domain="dashboard.example.com",
    prefers_border=True,
)

mcp = MCPServer("dashboard", extensions=[apps])
