from mcp.server.apps import Apps, client_supports_apps
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context

CLOCK_HTML = """\
<!doctype html>
<title>Clock</title>
<h1 id="now">...</h1>
<script>
  window.addEventListener("message", (event) => {
    const text = event.data?.result?.content?.[0]?.text;
    if (text) document.getElementById("now").textContent = text;
  });
</script>
"""

apps = Apps()


@apps.tool(resource_uri="ui://clock/app.html", description="The current time.")
def get_time(ctx: Context) -> str:
    now = "2026-06-26T12:00:00Z"
    if not client_supports_apps(ctx):
        return f"The time is {now}."
    return now


apps.add_html_resource("ui://clock/app.html", CLOCK_HTML, title="Clock")

mcp = MCPServer("clock", extensions=[apps])
