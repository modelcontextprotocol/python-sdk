from pathlib import Path

from mcp.server.apps import Apps
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.resources import FileResource

REPORT_HTML = Path(__file__).parent / "report.html"

apps = Apps()


@apps.tool(resource_uri="ui://report/app.html")
def refresh_report() -> str:
    """Refresh the report data."""
    return "report refreshed"


apps.add_resource(FileResource(uri="ui://report/app.html", name="report", path=REPORT_HTML))

mcp = MCPServer("report", extensions=[apps])
