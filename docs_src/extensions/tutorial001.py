from mcp.server.apps import Apps
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("demo", extensions=[Apps()])
