# Quickstart: Build a weather server

In this tutorial, we'll build a simple MCP weather server and connect it to a host.

## What we'll be building

We'll build a server that exposes two tools: `get_alerts` and `get_forecast`. Then we'll connect the server to an MCP host (in this case, VS Code with GitHub Copilot).

## Core MCP concepts

MCP servers can provide three main types of capabilities:

1. **[Resources](https://modelcontextprotocol.io/docs/learn/server-concepts#resources)**: File-like data that can be read by clients (like API responses or file contents)
2. **[Tools](https://modelcontextprotocol.io/docs/learn/server-concepts#tools)**: Functions that can be called by the LLM (with user approval)
3. **[Prompts](https://modelcontextprotocol.io/docs/learn/server-concepts#prompts)**: Pre-written templates that help users accomplish specific tasks

This tutorial will primarily focus on tools.

Let's get started with building our weather server! [You can find the complete code for what we'll be building here.](https://github.com/modelcontextprotocol/python-sdk/tree/main/examples/servers/quickstart-server/)

## Prerequisites

This quickstart assumes you have familiarity with:

- Python
- LLMs like Claude

Before starting, ensure your system meets these requirements:

- Python 3.10 or later installed
- Latest version of `uv` installed

## Set up your environment

First, let's install `uv` and set up our Python project and environment:

=== "macOS/Linux"

    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

=== "Windows"

    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

Make sure to restart your terminal afterwards to ensure that the `uv` command gets picked up.

Now, let's create and set up our project:

=== "macOS/Linux"

    ```bash
    # Create a new directory for our project
    uv init weather
    cd weather

    # Create virtual environment and activate it
    uv venv
    source .venv/bin/activate

    # Install dependencies
    uv add mcp httpx

    # Create our server file
    touch weather.py
    ```

=== "Windows"

    ```powershell
    # Create a new directory for our project
    uv init weather
    cd weather

    # Create virtual environment and activate it
    uv venv
    .venv\Scripts\activate

    # Install dependencies
    uv add mcp httpx

    # Create our server file
    new-item weather.py
    ```

Now let's dive into building your server.

## Building your server

### Importing packages and setting up the instance

Add these to the top of your `weather.py`:

<!-- snippet-source examples/servers/quickstart-server/weather.py#module_overview -->
```python
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

# Initialize MCP server
mcp = MCPServer("weather")

# Constants
NWS_API_BASE = "https://api.weather.gov"
USER_AGENT = "weather-app/1.0"
```
<!-- /snippet-source -->

The `MCPServer` class uses Python type hints and docstrings to automatically generate tool definitions, making it easy to create and maintain MCP tools.

### Helper functions

Next, let's add our helper functions for querying and formatting the data from the National Weather Service API:

<!-- snippet-source examples/servers/quickstart-server/weather.py#helper_functions -->
```python
async def make_nws_request(url: str) -> dict[str, Any] | None:
    """Make a request to the NWS API with proper error handling."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/geo+json"}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None


def format_alert(feature: dict[str, Any]) -> str:
    """Format an alert feature into a readable string."""
    props = feature["properties"]
    return f"""
Event: {props.get("event", "Unknown")}
Area: {props.get("areaDesc", "Unknown")}
Severity: {props.get("severity", "Unknown")}
Description: {props.get("description", "No description available")}
Instructions: {props.get("instruction", "No specific instructions provided")}
"""
```
<!-- /snippet-source -->

### Registering tools

Each tool is registered with the `@mcp.tool()` decorator, which uses the function's name, type hints, and docstring to generate the tool definition. Let's register our two weather tools:

<!-- snippet-source examples/servers/quickstart-server/weather.py#tool_implementations -->
```python
@mcp.tool()
async def get_alerts(state: str) -> str:
    """Get weather alerts for a US state.

    Args:
        state: Two-letter US state code (e.g. CA, NY)
    """
    url = f"{NWS_API_BASE}/alerts/active/area/{state}"
    data = await make_nws_request(url)

    if not data or "features" not in data:
        return "Unable to fetch alerts or no alerts found."

    if not data["features"]:
        return "No active alerts for this state."

    alerts = [format_alert(feature) for feature in data["features"]]
    return "\n---\n".join(alerts)


@mcp.tool()
async def get_forecast(latitude: float, longitude: float) -> str:
    """Get weather forecast for a location.

    Args:
        latitude: Latitude of the location
        longitude: Longitude of the location
    """
    # First get the forecast grid endpoint
    points_url = f"{NWS_API_BASE}/points/{latitude},{longitude}"
    points_data = await make_nws_request(points_url)

    if not points_data:
        return "Unable to fetch forecast data for this location."

    # Get the forecast URL from the points response
    forecast_url = points_data["properties"]["forecast"]
    forecast_data = await make_nws_request(forecast_url)

    if not forecast_data:
        return "Unable to fetch detailed forecast."

    # Format the periods into a readable forecast
    periods = forecast_data["properties"]["periods"]
    forecasts: list[str] = []
    for period in periods[:5]:  # Only show next 5 periods
        forecast = f"""
{period["name"]}:
Temperature: {period["temperature"]}°{period["temperatureUnit"]}
Wind: {period["windSpeed"]} {period["windDirection"]}
Forecast: {period["detailedForecast"]}
"""
        forecasts.append(forecast)

    return "\n---\n".join(forecasts)
```
<!-- /snippet-source -->

### Running the server

Finally, let's initialize and run the server:

<!-- snippet-source examples/servers/quickstart-server/weather.py#main_entrypoint -->
```python
def main() -> None:
    """Run the weather MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
```
<!-- /snippet-source -->

!!! important

    Always use `print(..., file=sys.stderr)` or the `logging` module instead of plain `print()` in stdio-based MCP servers. Standard output is reserved for JSON-RPC protocol messages, and writing to it with `print()` will corrupt the communication channel.

Your server is complete! Let's now test it from an existing MCP host.

## Testing your server in VS Code

[VS Code](https://code.visualstudio.com/) with [GitHub Copilot](https://github.com/features/copilot) can discover and invoke MCP tools via agent mode. [Copilot Free](https://github.com/features/copilot/plans) is sufficient to follow along.

!!! note

    Servers can connect to any client. We've chosen VS Code here for simplicity, but we also have a guide on [building your own client](client-quickstart.md) as well as a [list of other clients here](https://modelcontextprotocol.io/clients).

### Set up VS Code

1. Install [VS Code](https://code.visualstudio.com/) (version 1.99 or later).
2. Install the **GitHub Copilot** extension from the VS Code Extensions marketplace.
3. Sign in to your GitHub account when prompted.

### Configure the MCP server

Open your `weather` project in VS Code, then create a `.vscode/mcp.json` file in the project root:

```json
{
  "servers": {
    "weather": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "weather.py"]
    }
  }
}
```

VS Code may prompt you to trust the MCP server when it detects this file. If prompted, confirm to start the server.

To verify, run **MCP: List Servers** from the Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`). The `weather` server should show a running status.

### Use the tools

1. Open **Copilot Chat** (`Ctrl+Alt+I` / `Ctrl+Cmd+I`).
2. Select **Agent** mode from the mode selector at the top of the chat panel.
3. Click the **Tools** button to confirm `get_alerts` and `get_forecast` appear.
4. Try these prompts:
   - "What's the weather in Sacramento?"
   - "What are the active weather alerts in Texas?"

!!! note

    Since this is the US National Weather Service, the queries will only work for US locations.

## What's happening under the hood

When you ask a question:

1. The client sends your question to the LLM
2. The LLM analyzes the available tools and decides which one(s) to use
3. The client executes the chosen tool(s) through the MCP server
4. The results are sent back to the LLM
5. The LLM formulates a natural language response
6. The response is displayed to you

## Troubleshooting

??? "VS Code integration issues"

    **Server not appearing or fails to start**

    1. Verify you have VS Code 1.99 or later (`Help > About`) and that GitHub Copilot is installed.
    2. Verify the server runs without errors: run `uv run weather.py` in the `weather` directory — the process should start and wait for input. Press `Ctrl+C` to exit.
    3. Check the server logs: in **MCP: List Servers**, select the server and choose **Show Output**.
    4. If the `uv` command is not found, use the full path to the `uv` executable in `.vscode/mcp.json`.

    **Tools don't appear in Copilot Chat**

    1. Confirm you're in **Agent** mode (not Ask or Edit mode).
    2. Run **MCP: Reset Cached Tools** from the Command Palette, then recheck the **Tools** list.

??? "Weather API issues"

    **Error: Failed to retrieve grid point data**

    This usually means either:

    1. The coordinates are outside the US
    2. The NWS API is having issues
    3. You're being rate limited

    Fix:

    - Verify you're using US coordinates
    - Add a small delay between requests
    - Check the NWS API status page

    **Error: No active alerts for [STATE]**

    This isn't an error — it just means there are no current weather alerts for that state. Try a different state or check during severe weather.

## Next steps

Now that your server is running locally, here are some ways to go further:

- **[Building a client](client-quickstart.md)** — Learn how to build your own MCP client that can connect to your server
- **[Example servers](https://modelcontextprotocol.io/examples)** — Check out our gallery of official MCP servers and implementations
- **[Debugging Guide](https://modelcontextprotocol.io/legacy/tools/debugging)** — Learn how to effectively debug MCP servers and integrations
- **[Building MCP with LLMs](https://modelcontextprotocol.io/tutorials/building-mcp-with-llms)** — Learn how to use LLMs like Claude to speed up your MCP development
