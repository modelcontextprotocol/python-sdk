from mcp.server import FastMCP 

# from dotenv import load_dotenv
import os
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import base as mcp_messages

mcp = FastMCP("weather") # No reason to initialize stateless 




@mcp.prompt()
def weather_system_prompt() -> mcp_messages.SystemMessage:
    """
    Creates a prompt asking an AI to weather 
    Args:
        None: None
    """
    
    return mcp_messages.SystemMessage("""You are a helpful weather agent. Your job is to answer weather-related questions clearly and simply. If the user asks for the weather in a city, you tell the current weather, temperature, and a short description like "sunny," "cloudy," or "rainy." If you don’t know the answer, say "Sorry, I don’t have that information.""")


mcp_app = mcp.streamable_http_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("system_prompt:mcp_app", host="0.0.0.0", port=8002, reload=True)