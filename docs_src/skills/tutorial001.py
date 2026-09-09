import hashlib
from typing import Any

from mcp_types import INVALID_PARAMS

from mcp.server.context import ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.resources import TextResource
from mcp.server.skills import Skills
from mcp.shared.exceptions import MCPError
from mcp.shared.skills import (
    GetSkillParams,
    GetSkillResult,
    ListSkillsParams,
    ListSkillsResult,
    Skill,
    SkillResource,
)

SKILL_URI = "skill://git-workflow/SKILL.md"
SKILL_MD = """\
---
name: git-workflow
description: Follow this team's Git conventions for branching and commits
---

Branch from `main` using `type/short-description`. Write commit subjects in the
imperative mood, under 72 characters.
"""

GIT_WORKFLOW = Skill(
    uri=SKILL_URI,
    frontmatter={"name": "git-workflow", "description": "Follow this team's Git conventions for branching and commits"},
    resources=[
        SkillResource(
            uri=SKILL_URI,
            digest=f"sha256:{hashlib.sha256(SKILL_MD.encode()).hexdigest()}",
            size=len(SKILL_MD.encode()),
        )
    ],
)


async def list_skills(ctx: ServerRequestContext[Any, Any], params: ListSkillsParams) -> ListSkillsResult:
    return ListSkillsResult(skills=[GIT_WORKFLOW])


async def get_skill(ctx: ServerRequestContext[Any, Any], params: GetSkillParams) -> GetSkillResult:
    if params.uri != SKILL_URI:
        raise MCPError(code=INVALID_PARAMS, message=f"unknown skill: {params.uri}")
    return GetSkillResult(skill=GIT_WORKFLOW)


mcp = MCPServer("catalog", extensions=[Skills(list_skills=list_skills, get_skill=get_skill)])
mcp.add_resource(TextResource(uri=SKILL_URI, name="SKILL.md", mime_type="text/markdown", text=SKILL_MD))
