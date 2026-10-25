from pathlib import Path

import anyio
import yaml

from mcp.server.mcpserver import MCPServer
from mcp.server.skills import FilesystemSkillProvider, SkillCatalog


async def build_server(root: Path) -> MCPServer:
    catalog = await SkillCatalog.load(
        FilesystemSkillProvider(root),
        parse_frontmatter=yaml.safe_load,
        directory_read=True,
    )
    return MCPServer("skills", extensions=[catalog])


async def main() -> None:
    server = await build_server(Path(__file__).parent / "skills")
    await server.run_stdio_async()


if __name__ == "__main__":
    anyio.run(main)
