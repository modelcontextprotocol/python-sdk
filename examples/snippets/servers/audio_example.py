from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Audio

mcp = FastMCP("Audio Example")


@mcp.tool()
def get_audio_from_file(file_path: str) -> Audio:
    """Return audio from a file path (format auto-detected from extension)."""
    return Audio(path=file_path)


@mcp.tool()
def get_audio_from_bytes(raw_audio: bytes) -> Audio:
    """Return audio from raw bytes with explicit format."""
    return Audio(data=raw_audio, format="wav")
