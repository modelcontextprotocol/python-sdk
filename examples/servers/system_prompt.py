from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import base as mcp_messages

mcp = FastMCP("weather")


@mcp.prompt()
def weather_system_prompt() -> mcp_messages.SystemMessage:
    """
    Creates a prompt asking an AI to weather
    Args:
        None: None
    """

    return mcp_messages.SystemMessage(
        "You are a helpful weather agent. You answer questions clearly and simply. "
        "If you don’t know something, say you don’t have that information."
    )


mcp_app = mcp.streamable_http_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("system_prompt:mcp_app", host="0.0.0.0", port=8002, reload=True)
