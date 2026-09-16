"""Client-side convenience wrappers for the Skills extension (SEP-2640).

SEP-2640 needs no client-side method registration: `skills/list`, `skills/get`,
and `resources/directory/read` are ordinary vendor requests sent through
`ClientSession.send_request`, exactly like [Extension verbs](../advanced/extensions.md#extension-verbs).
The functions below are the thin, named wrappers SEP-2640's "SDKs: Convenience
Wrappers" section recommends — each validates the server's advertised support
before sending, and `list_skills`/`read_directory` follow `nextCursor` to
completion so a caller sees one page's worth of ergonomics regardless of how
many requests it took.

    async with Client("http://localhost:8000/mcp") as client:
        for skill in await list_skills(client.session):
            print(skill.uri, skill.frontmatter["description"])
"""

from __future__ import annotations

from mcp_types import ReadResourceResult, Resource

from mcp.client.session import ClientSession
from mcp.shared.skills import (
    EXTENSION_ID,
    GetSkillParams,
    GetSkillRequest,
    GetSkillResult,
    ListSkillsParams,
    ListSkillsRequest,
    ListSkillsResult,
    ReadDirectoryParams,
    ReadDirectoryRequest,
    ReadDirectoryResult,
    Skill,
    validate_directory_result,
    validate_list_result,
    validate_skill,
)
from mcp.shared.skills import verify_skill_resource as verify_skill_resource

__all__ = ["get_skill", "list_skills", "read_directory", "read_skill_uri", "verify_skill_resource"]


def _require_extension(session: ClientSession, *, directory_read: bool = False) -> None:
    capabilities = session.server_capabilities
    settings = (capabilities.extensions or {}).get(EXTENSION_ID) if capabilities else None
    if settings is None:
        raise ValueError(f"server does not advertise the {EXTENSION_ID!r} extension")
    if directory_read and not settings.get("directoryRead"):
        raise ValueError(f"server does not advertise {EXTENSION_ID!r}'s directoryRead setting")


async def list_skills(session: ClientSession, params: ListSkillsParams | None = None) -> list[Skill]:
    """Call `skills/list`, following `nextCursor` to completion, and validate the result.

    Raises:
        ValueError: If the server doesn't advertise the Skills extension, or
            its response is not SEP-2640 conformant.
    """
    _require_extension(session)
    base = params if params is not None else ListSkillsParams()
    cursor = base.cursor
    skills: list[Skill] = []
    seen_cursors: set[str] = {cursor} if cursor is not None else set()
    while True:
        page = await session.send_request(
            ListSkillsRequest(params=base.model_copy(update={"cursor": cursor})), ListSkillsResult
        )
        validate_list_result(page)
        skills.extend(page.skills)
        if page.next_cursor is None:
            return skills
        if page.next_cursor in seen_cursors:
            raise ValueError(f"server repeated skills/list pagination cursor {page.next_cursor!r}")
        seen_cursors.add(page.next_cursor)
        cursor = page.next_cursor


async def get_skill(session: ClientSession, uri: str) -> Skill:
    """Call `skills/get` for `uri` and validate the result.

    Unlike `list_skills`, this succeeds for a skill absent from any listing —
    per SEP-2640, a server MUST answer `skills/get` for every skill it serves.

    Raises:
        ValueError: If the server doesn't advertise the Skills extension, its
            response names a different skill, or the skill is not conformant.
    """
    _require_extension(session)
    result = await session.send_request(GetSkillRequest(params=GetSkillParams(uri=uri)), GetSkillResult)
    if result.skill.uri != uri:
        raise ValueError(f"server returned skill {result.skill.uri!r} for requested {uri!r}")
    validate_skill(result.skill)
    return result.skill


async def read_skill_uri(session: ClientSession, uri: str) -> ReadResourceResult:
    """Read a skill file's content via `resources/read`.

    A thin, discoverable alias: works for any `skill://` (or other-scheme)
    file regardless of whether the skill was ever enumerated. Verify the
    result against a held `Skill` entry with `verify_skill_resource` before
    treating it as trusted content — this call does not verify anything itself.
    """
    return await session.read_resource(uri)


async def read_directory(session: ClientSession, uri: str, params: ReadDirectoryParams | None = None) -> list[Resource]:
    """Call `resources/directory/read` for `uri`, following `nextCursor` to completion.

    Raises:
        ValueError: If the server doesn't advertise the `directoryRead`
            setting, or its response is not a valid child listing of `uri`.
    """
    _require_extension(session, directory_read=True)
    base = params if params is not None else ReadDirectoryParams(uri=uri)
    cursor = base.cursor
    resources: list[Resource] = []
    seen_cursors: set[str] = {cursor} if cursor is not None else set()
    while True:
        page = await session.send_request(
            ReadDirectoryRequest(params=base.model_copy(update={"uri": uri, "cursor": cursor})), ReadDirectoryResult
        )
        validate_directory_result(uri, page)
        resources.extend(page.resources)
        if page.next_cursor is None:
            return resources
        if page.next_cursor in seen_cursors:
            raise ValueError(f"server repeated resources/directory/read pagination cursor {page.next_cursor!r}")
        seen_cursors.add(page.next_cursor)
        cursor = page.next_cursor
