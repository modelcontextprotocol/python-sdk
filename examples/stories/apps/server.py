"""MCP Apps: a tool bound to a `ui://` resource the host renders as an interactive surface.

`Apps` is an opt-in `Extension` passed to `MCPServer(extensions=[...])`. The
`@apps.tool(resource_uri=...)` decorator stamps `_meta.ui.resourceUri` onto the
tool; `add_html_resource` registers the matching `ui://` HTML resource. The tool
degrades gracefully: `client_supports_apps(ctx)` reports whether the client
negotiated Apps, so it returns text-only output otherwise.
"""

from mcp.server.apps import Apps, client_supports_apps
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from stories._hosting import run_server_from_args

RESOURCE_URI = "ui://get-time/app.html"
CLOCK_HTML = """<!doctype html>
<title>Current time</title>
<h1 id="now">…</h1>
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


def build_server() -> MCPServer:
    apps = Apps()

    @apps.tool(resource_uri=RESOURCE_URI, title="Get Time", description="Return the current time.")
    def get_time(ctx: Context) -> str:
        now = "2026-06-26T00:00:00Z"
        if not client_supports_apps(ctx):
            return f"The time is {now}."
        return now

    apps.add_html_resource(RESOURCE_URI, CLOCK_HTML, title="Clock")
    return MCPServer("apps-example", extensions=[apps])


if __name__ == "__main__":
    run_server_from_args(build_server)
