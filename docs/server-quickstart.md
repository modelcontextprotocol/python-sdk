# Quickstart: Build a weather server

In this tutorial, we'll build a simple MCP weather server and connect it to a host, Claude for Desktop.

## What we'll be building

We'll build a server that exposes two tools: `get_alerts` and `get_forecast`. Then we'll connect the server to an MCP host (in this case, Claude for Desktop).

!!! note

    Servers can connect to any client. We've chosen Claude for Desktop here for simplicity, but we also have guides on [building your own client](client-quickstart.md) as well as a [list of other clients here](https://modelcontextprotocol.io/clients).

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

Your server is complete! Let's now test it from an existing MCP host, Claude for Desktop.

## Testing your server with Claude for Desktop

!!! note

    Claude for Desktop is not yet available on Linux. Linux users can proceed to the [Building a client](client-quickstart.md) tutorial to build an MCP client that connects to the server we just built.

First, make sure you have Claude for Desktop installed. [You can install the latest version here.](https://claude.ai/download) If you already have Claude for Desktop, **make sure it's updated to the latest version.**

We'll need to configure Claude for Desktop for whichever MCP servers you want to use. To do this, open your Claude for Desktop App configuration at `~/Library/Application Support/Claude/claude_desktop_config.json` in a text editor. Make sure to create the file if it doesn't exist.

For example, if you have [VS Code](https://code.visualstudio.com/) installed:

=== "macOS/Linux"

    ```bash
    code ~/Library/Application\ Support/Claude/claude_desktop_config.json
    ```

=== "Windows"

    ```powershell
    code $env:AppData\Claude\claude_desktop_config.json
    ```

You'll then add your servers in the `mcpServers` key. The MCP UI elements will only show up in Claude for Desktop if at least one server is properly configured.

In this case, we'll add our single weather server like so:

=== "macOS/Linux"

    ```json
    {
      "mcpServers": {
        "weather": {
          "command": "uv",
          "args": [
            "--directory",
            "/ABSOLUTE/PATH/TO/PARENT/FOLDER/weather",
            "run",
            "weather.py"
          ]
        }
      }
    }
    ```

=== "Windows"

    ```json
    {
      "mcpServers": {
        "weather": {
          "command": "uv",
          "args": [
            "--directory",
            "C:\\ABSOLUTE\\PATH\\TO\\PARENT\\FOLDER\\weather",
            "run",
            "weather.py"
          ]
        }
      }
    }
    ```

!!! warning

    You may need to put the full path to the `uv` executable in the `command` field. You can get this by running `which uv` on macOS/Linux or `where uv` on Windows.

!!! note

    Make sure you pass in the absolute path to your server. You can get this by running `pwd` on macOS/Linux or `cd` on Windows Command Prompt. On Windows, remember to use double backslashes (`\\`) or forward slashes (`/`) in the JSON path.

This tells Claude for Desktop:

1. There's an MCP server named "weather"
2. To launch it by running `uv --directory /ABSOLUTE/PATH/TO/PARENT/FOLDER/weather run weather.py`

Save the file, and restart **Claude for Desktop**.

### Test with commands

Let's make sure Claude for Desktop is picking up the two tools we've exposed in our `weather` server. You can do this by looking for the "Add files, connectors, and more" icon.

After clicking on the plus icon, hover over the "Connectors" menu. You should see the `weather` server listed.

If your server isn't being picked up by Claude for Desktop, proceed to the [Troubleshooting](#troubleshooting) section for debugging tips.

If the server has shown up in the "Connectors" menu, you can now test your server by running the following commands in Claude for Desktop:

- What's the weather in Sacramento?
- What are the active weather alerts in Texas?

!!! note

    Since this is the US National Weather Service, the queries will only work for US locations.

## What's happening under the hood

When you ask a question:

1. The client sends your question to Claude
2. Claude analyzes the available tools and decides which one(s) to use
3. The client executes the chosen tool(s) through the MCP server
4. The results are sent back to Claude
5. Claude formulates a natural language response
6. The response is displayed to you!

## Troubleshooting

??? "Claude for Desktop integration issues"

    **Getting logs from Claude for Desktop**

    Claude.app logging related to MCP is written to log files in `~/Library/Logs/Claude`:

    - `mcp.log` will contain general logging about MCP connections and connection failures.
    - Files named `mcp-server-SERVERNAME.log` will contain error (stderr) logging from the named server.

    You can run the following command to list recent logs and follow along with any new ones:

    ```bash
    # Check Claude's logs for errors
    tail -n 20 -f ~/Library/Logs/Claude/mcp*.log
    ```

    **Server not showing up in Claude**

    1. Check your `claude_desktop_config.json` file syntax
    2. Make sure the path to your project is absolute and not relative
    3. Restart Claude for Desktop completely

    !!! warning

        To properly restart Claude for Desktop, you must fully quit the application:

        - **Windows**: Right-click the Claude icon in the system tray (which may be hidden in the "hidden icons" menu) and select "Quit" or "Exit".
        - **macOS**: Use Cmd+Q or select "Quit Claude" from the menu bar.

        Simply closing the window does not fully quit the application, and your MCP server configuration changes will not take effect.

    **Tool calls failing silently**

    If Claude attempts to use the tools but they fail:

    1. Check Claude's logs for errors
    2. Verify your server builds and runs without errors
    3. Try restarting Claude for Desktop

    **None of this is working. What do I do?**

    Please refer to our [debugging guide](https://modelcontextprotocol.io/legacy/tools/debugging) for better debugging tools and more detailed guidance.

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

!!! note

    For more advanced troubleshooting, check out our guide on [Debugging MCP](https://modelcontextprotocol.io/legacy/tools/debugging).

## Next steps

Now that your server is running locally, here are some ways to go further:

- **[Building a client](client-quickstart.md)** — Learn how to build your own MCP client that can connect to your server
- **[Example servers](https://modelcontextprotocol.io/examples)** — Check out our gallery of official MCP servers and implementations
- **[Debugging Guide](https://modelcontextprotocol.io/legacy/tools/debugging)** — Learn how to effectively debug MCP servers and integrations
- **[Building MCP with LLMs](https://modelcontextprotocol.io/tutorials/building-mcp-with-llms)** — Learn how to use LLMs like Claude to speed up your MCP development
