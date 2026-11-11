"""The Skills extension (`io.modelcontextprotocol/skills`, SEP-2640).

SEP-2640 defines a convention for serving Agent Skills over MCP using the
Resources primitive: a skill is a directory of files, conventionally exposed
under the `skill://` scheme, and enumerated and fetched through two required
methods (`skills/list`, `skills/get`) plus one optional one
(`resources/directory/read`). See
https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2640.

`Skills` is the protocol-level plumbing: request/response handling, SEP-2640
conformance validation, and capability advertisement. A server author supplies
handlers that answer `skills/list`/`skills/get`/`resources/directory/read`
however their catalog is stored, and serves the underlying `skill://` file
content through the server's ordinary resource-registration APIs.

To serve skills from a directory (or any other source of files) without writing
handlers, use `SkillCatalog` with a `SkillProvider` such as `FilesystemSkillProvider`.

    async def list_skills(ctx, params):
        return ListSkillsResult(skills=[...])

    async def get_skill(ctx, params):
        if params.uri != "skill://git-workflow/SKILL.md":
            raise MCPError(code=INVALID_PARAMS, message="unknown skill")
        return GetSkillResult(skill=...)

    mcp = MCPServer("catalog", extensions=[Skills(list_skills=list_skills, get_skill=get_skill)])
"""

# The handler aliases were importable from `mcp.server.skills` when it was a single module.
from mcp.server.skills._extension import GetSkillHandler as GetSkillHandler
from mcp.server.skills._extension import ListSkillsHandler as ListSkillsHandler
from mcp.server.skills._extension import ReadDirectoryHandler as ReadDirectoryHandler
from mcp.server.skills._extension import Skills
from mcp.server.skills.catalog import SkillCatalog
from mcp.server.skills.filesystem import FilesystemSkillProvider
from mcp.server.skills.provider import SkillProvider

__all__ = ["Skills", "SkillCatalog", "SkillProvider", "FilesystemSkillProvider"]
