from mcp.server import MCPServer

mcp = MCPServer("Weather")


class Station:
    def __init__(self, name: str, online: bool):
        self.name = name
        self.online = online


@mcp.tool()
def get_station(name: str) -> Station:
    """Look up a weather station by name."""
    return Station(name=name, online=True)
