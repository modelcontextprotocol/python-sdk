from mcp.server.apps import Apps, client_supports_apps
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context

CLOCK_HTML = """\
<!doctype html>
<title>Clock</title>
<h1 id="now">...</h1>
<script>
  const parent = window.parent;
  let initialized = false;
  window.addEventListener("message", (event) => {
    if (event.source !== parent || event.data?.jsonrpc !== "2.0") return;
    if (event.data.id === 1 && event.data.result?.protocolVersion) {
      parent.postMessage({jsonrpc: "2.0", method: "ui/notifications/initialized"}, "*");
      initialized = true;
      return;
    }
    if (!initialized || event.data.method !== "ui/notifications/tool-result") return;
    const text = event.data.params?.content?.[0]?.text;
    if (typeof text === "string") document.getElementById("now").textContent = text;
  });
  parent.postMessage({
    jsonrpc: "2.0",
    id: 1,
    method: "ui/initialize",
    params: {
      appInfo: {name: "clock", version: "1.0.0"},
      appCapabilities: {},
      protocolVersion: "2026-01-26"
    }
  }, "*");
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
