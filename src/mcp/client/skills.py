"""Client-side Skills extension (SEP-2640).

`Skills` is an opt-in [`ClientExtension`](../advanced/extensions.md) for talking
to a skills catalog server. Register it with `Client(extensions=[Skills()])`,
then call `bind(client)` for the SEP-2640 verbs — `list_skills`, `get_skill`,
`read_skill_uri`, and `read_directory` — tied to that connection:

    async with Client("http://localhost:8000/mcp", extensions=[skills := Skills()]) as client:
        for skill in await skills.bind(client).list_skills():
            print(skill.uri, skill.frontmatter["description"])

`bind(client)` returns a `BoundSkills`. Its catalog verbs — `list_skills`,
`get_skill`, and `read_directory` — check that the server advertises the
extension and validate its response; `list_skills` and `read_directory` follow
`nextCursor` to completion, so one call returns every page's results.
`read_skill_uri` is a thin `resources/read` alias that does neither — verify its
result with `verify_skill_resource`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_types import ReadResourceResult, Resource

from mcp.client.extension import ClientExtension
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

if TYPE_CHECKING:
    from mcp.client.client import Client

__all__ = ["BoundSkills", "Skills", "verify_skill_resource"]


class Skills(ClientExtension):
    """The client-side Skills extension: register, then `bind` for typed verbs.

    Pass an instance to `Client(extensions=[Skills()])` — this advertises
    `io.modelcontextprotocol/skills` under the client's capabilities — and call
    `bind(client)` once the client is connected for a `BoundSkills` handle.
    """

    identifier = EXTENSION_ID

    def bind(self, client: Client) -> BoundSkills:
        """Return the SEP-2640 verbs bound to `client`'s connected session.

        Raises:
            RuntimeError: If `client` has not entered its `async with` block yet.
        """
        return BoundSkills(client.session)


class BoundSkills:
    """The SEP-2640 verbs bound to one connected session.

    Obtain it from `Skills.bind(client)`. The catalog verbs — `list_skills`,
    `get_skill`, and `read_directory` — check that the server advertises the
    extension and validate its response against the SEP-2640 conformance rules
    before returning; `list_skills` and `read_directory` also follow
    `nextCursor` to completion. `read_skill_uri` is the exception: a thin
    `resources/read` alias that neither checks advertisement nor validates —
    pair it with `verify_skill_resource`.
    """

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    def _require_extension(self, *, directory_read: bool = False) -> None:
        capabilities = self._session.server_capabilities
        settings = (capabilities.extensions or {}).get(EXTENSION_ID) if capabilities else None
        if settings is None:
            raise ValueError(f"server does not advertise the {EXTENSION_ID!r} extension")
        if directory_read and not settings.get("directoryRead"):
            raise ValueError(f"server does not advertise {EXTENSION_ID!r}'s directoryRead setting")

    async def list_skills(self, params: ListSkillsParams | None = None) -> list[Skill]:
        """Call `skills/list`, following `nextCursor` to completion, and validate the result.

        Raises:
            ValueError: If the server doesn't advertise the Skills extension, its
                response is not SEP-2640 conformant, or it repeats a pagination cursor.
            MCPError: If the server returns an error response.
        """
        self._require_extension()
        base = params if params is not None else ListSkillsParams()
        cursor = base.cursor
        skills: list[Skill] = []
        seen_cursors: set[str] = {cursor} if cursor is not None else set()
        while True:
            page = await self._session.send_request(
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

    async def get_skill(self, uri: str) -> Skill:
        """Call `skills/get` for `uri` and validate the result.

        Unlike `list_skills`, this succeeds for a skill absent from any listing —
        per SEP-2640, a server MUST answer `skills/get` for every skill it serves.

        Raises:
            ValueError: If the server doesn't advertise the Skills extension, its
                response names a different skill, or the skill is not conformant.
            MCPError: If the server returns an error response, such as `-32602`
                for a URI it does not serve.
        """
        self._require_extension()
        result = await self._session.send_request(GetSkillRequest(params=GetSkillParams(uri=uri)), GetSkillResult)
        if result.skill.uri != uri:
            raise ValueError(f"server returned skill {result.skill.uri!r} for requested {uri!r}")
        validate_skill(result.skill)
        return result.skill

    async def read_skill_uri(self, uri: str) -> ReadResourceResult:
        """Read a skill file's content via `resources/read`.

        A thin, discoverable alias: works for any `skill://` (or other-scheme)
        file regardless of whether the skill was ever enumerated. Verify the
        result against a held `Skill` entry with `verify_skill_resource` before
        treating it as trusted content — this call does not verify anything itself.

        Raises:
            MCPError: If the server returns an error response.
            RuntimeError: If the server returns an `InputRequiredResult`; this
                alias does not drive the input-required loop.
        """
        return await self._session.read_resource(uri)

    async def read_directory(self, uri: str, params: ReadDirectoryParams | None = None) -> list[Resource]:
        """Call `resources/directory/read` for `uri`, following `nextCursor` to completion.

        Raises:
            ValueError: If the server doesn't advertise the `directoryRead`
                setting, its response is not a valid child listing of `uri`, or
                it repeats a pagination cursor.
            MCPError: If the server returns an error response.
        """
        self._require_extension(directory_read=True)
        base = params if params is not None else ReadDirectoryParams(uri=uri)
        cursor = base.cursor
        resources: list[Resource] = []
        seen_cursors: set[str] = {cursor} if cursor is not None else set()
        while True:
            page = await self._session.send_request(
                ReadDirectoryRequest(params=base.model_copy(update={"uri": uri, "cursor": cursor})),
                ReadDirectoryResult,
            )
            validate_directory_result(uri, page)
            resources.extend(page.resources)
            if page.next_cursor is None:
                return resources
            if page.next_cursor in seen_cursors:
                raise ValueError(f"server repeated resources/directory/read pagination cursor {page.next_cursor!r}")
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor
