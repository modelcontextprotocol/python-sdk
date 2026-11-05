"""Tests for `SkillCatalog` (`mcp.server.skills.catalog`): the provider-backed Skills extension.

Every test drives a real `MCPServer` through an in-memory `Client`. The provider is a dict of
bytes and the frontmatter parser a `key: value` stand-in, so the SDK's no-YAML-dependency
stance holds in the tests too.
"""

import base64
import datetime
import hashlib
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from mcp_types import INTERNAL_ERROR, INVALID_PARAMS, BlobResourceContents, TextResourceContents
from pydantic import BaseModel, ConfigDict

import mcp.server.skills as skills_package
from mcp.client.client import Client
from mcp.client.extensions.skills import Skills as ClientSkills
from mcp.server.mcpserver import MCPServer
from mcp.server.skills import (
    FilesystemSkillProvider,
    GetSkillHandler,
    ListSkillsHandler,
    ReadDirectoryHandler,
    SkillCatalog,
    SkillProvider,
)
from mcp.shared.exceptions import MCPError
from mcp.shared.skills import (
    MAX_RESOURCES_PER_SKILL,
    MAX_TOTAL_SIZE,
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
)

pytestmark = pytest.mark.anyio

CATALOG_LOGGER = "mcp.server.skills.catalog"


class _RawResult(BaseModel):
    """Captures every wire field so a test can see which cache fields were sent."""

    model_config = ConfigDict(extra="allow")


class _MemoryProvider:
    """A `SkillProvider` over a dict. `listing` overrides what `list_files` reports."""

    def __init__(self, files: Mapping[str, bytes], listing: Sequence[str] | None = None) -> None:
        self.files = dict(files)
        self._listing = listing

    async def list_files(self) -> Sequence[str]:
        return list(self.files) if self._listing is None else self._listing

    async def read_file(self, path: str) -> bytes:
        return self.files[path]


def _parse(text: str) -> Mapping[str, Any]:
    """A stand-in for `yaml.safe_load` that understands flat `key: value` lines."""
    result: dict[str, Any] = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(f"not a `key: value` line: {line!r}")
        result[key.strip()] = value.strip()
    return result


def _skill_md(name: str, description: str = "Does the thing", extra: str = "") -> bytes:
    return f"---\nname: {name}\ndescription: {description}\n{extra}---\nBody for {name}.\n".encode()


def _digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


async def _listed(catalog: SkillCatalog) -> list[Skill]:
    server = MCPServer("skills", extensions=[catalog])
    async with Client(server, extensions=[ClientSkills()]) as client:
        return list(await client.extension(ClientSkills).list_skills())


async def _server(files: Mapping[str, bytes], **options: Any) -> MCPServer:
    catalog = await SkillCatalog.load(_MemoryProvider(files), parse_frontmatter=_parse, **options)
    return MCPServer("skills", extensions=[catalog])


async def test_list_skills_returns_every_valid_skill_sorted_with_complete_manifests() -> None:
    """SEP-2640: `skills/list` enumerates skills, each with a manifest of `{uri, digest, size}`."""
    skill_md = _skill_md("git-workflow")
    guide = b"# Conventions\n"
    server = await _server(
        {
            "zebra/SKILL.md": _skill_md("zebra"),
            "git-workflow/SKILL.md": skill_md,
            "git-workflow/references/conventions.md": guide,
            "outside-any-skill.txt": b"ignored",
        }
    )
    async with Client(server, extensions=[ClientSkills()]) as client:
        skills = await client.extension(ClientSkills).list_skills()

    assert [skill.uri for skill in skills] == ["skill://git-workflow/SKILL.md", "skill://zebra/SKILL.md"]
    assert skills[0].frontmatter == {"name": "git-workflow", "description": "Does the thing"}
    assert isinstance(skills[0].resources, list)
    assert [(r.uri, r.digest, r.size) for r in skills[0].resources] == [
        ("skill://git-workflow/SKILL.md", _digest(skill_md), len(skill_md)),
        ("skill://git-workflow/references/conventions.md", _digest(guide), len(guide)),
    ]


async def test_get_skill_returns_the_same_entry_as_the_listing() -> None:
    """SEP-2640: `skills/get` answers for a single skill by URI."""
    server = await _server({"git-workflow/SKILL.md": _skill_md("git-workflow")})
    async with Client(server, extensions=[ClientSkills()]) as client:
        listed = (await client.extension(ClientSkills).list_skills())[0]
        fetched = await client.extension(ClientSkills).get_skill(listed.uri)
    assert fetched == listed


async def test_get_skill_rejects_an_unknown_uri_with_invalid_params() -> None:
    """SEP-2640: an unknown skill URI is Invalid params (-32602)."""
    server = await _server({"git-workflow/SKILL.md": _skill_md("git-workflow")})
    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(
                GetSkillRequest(params=GetSkillParams(uri="skill://other/SKILL.md")), GetSkillResult
            )
    assert exc_info.value.code == INVALID_PARAMS


async def test_list_skills_rejects_a_cursor_because_the_catalog_never_issues_one() -> None:
    """SDK-defined: the catalog answers on a single page, so any cursor is Invalid params."""
    server = await _server({"git-workflow/SKILL.md": _skill_md("git-workflow")})
    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(
                ListSkillsRequest(params=ListSkillsParams(cursor="page-2")), ListSkillsResult
            )
    assert exc_info.value.code == INVALID_PARAMS


async def test_a_nested_skill_is_listed_and_its_files_also_belong_to_the_parent_manifest() -> None:
    """SEP-2640: a skill's files are everything under its directory, nested skills included."""
    server = await _server(
        {
            "acme/SKILL.md": _skill_md("acme"),
            "acme/billing/SKILL.md": _skill_md("billing"),
            "acme/billing/rules.md": b"rules",
        }
    )
    async with Client(server, extensions=[ClientSkills()]) as client:
        skills = {skill.uri: skill for skill in await client.extension(ClientSkills).list_skills()}

    assert sorted(skills) == ["skill://acme/SKILL.md", "skill://acme/billing/SKILL.md"]
    assert isinstance(skills["skill://acme/SKILL.md"].resources, list)
    assert [r.uri for r in skills["skill://acme/SKILL.md"].resources] == [
        "skill://acme/SKILL.md",
        "skill://acme/billing/SKILL.md",
        "skill://acme/billing/rules.md",
    ]
    assert isinstance(skills["skill://acme/billing/SKILL.md"].resources, list)
    assert [r.uri for r in skills["skill://acme/billing/SKILL.md"].resources] == [
        "skill://acme/billing/SKILL.md",
        "skill://acme/billing/rules.md",
    ]


async def test_a_skills_files_exclude_siblings_that_only_share_a_name_prefix() -> None:
    """SDK-defined: a manifest holds only what is under `acme/`, not `acme-tools/`, `acme0/` or `acme.md`.

    The provider lists in reverse order, so the result can't depend on the listing order.
    """
    files = {
        "acme/SKILL.md": _skill_md("acme"),
        "acme/guide.md": b"guide",
        "acme-tools/SKILL.md": _skill_md("acme-tools"),
        "acme0/SKILL.md": _skill_md("acme0"),
        "acme.md": b"loose",
    }
    provider = _MemoryProvider(files, listing=sorted(files, reverse=True))
    catalog = await SkillCatalog.load(provider, parse_frontmatter=_parse)
    async with Client(MCPServer("skills", extensions=[catalog]), extensions=[ClientSkills()]) as client:
        skills = {skill.uri: skill for skill in await client.extension(ClientSkills).list_skills()}

    assert isinstance(skills["skill://acme/SKILL.md"].resources, list)
    assert [r.uri for r in skills["skill://acme/SKILL.md"].resources] == [
        "skill://acme/SKILL.md",
        "skill://acme/guide.md",
    ]


async def test_hidden_files_and_directories_are_never_listed_or_served() -> None:
    """SDK-defined (matches typescript-sdk #3047): a path segment starting with `.` is skipped entirely."""
    server = await _server(
        {
            "git-workflow/SKILL.md": _skill_md("git-workflow"),
            "git-workflow/.env": b"SECRET=1",
            "git-workflow/references/.hidden/notes.md": b"hidden",
            "git-workflow/references/visible.md": b"visible",
            ".dotted/SKILL.md": _skill_md("dotted"),
        }
    )
    async with Client(server, extensions=[ClientSkills()]) as client:
        skills = await client.extension(ClientSkills).list_skills()
        served = [resource.uri for resource in (await client.list_resources()).resources]

    assert [skill.uri for skill in skills] == ["skill://git-workflow/SKILL.md"]
    assert isinstance(skills[0].resources, list)
    assert [r.uri for r in skills[0].resources] == [
        "skill://git-workflow/SKILL.md",
        "skill://git-workflow/references/visible.md",
    ]
    assert served == ["skill://git-workflow/SKILL.md", "skill://git-workflow/references/visible.md"]


@pytest.mark.parametrize(
    ("skill_md", "path"),
    [
        pytest.param(b"name: bad\ndescription: d\n", "bad/SKILL.md", id="no-opening-delimiter"),
        pytest.param(b"---\nname: bad\ndescription: d\n", "bad/SKILL.md", id="unterminated-frontmatter"),
        pytest.param(b"---\nnot a mapping line\n---\n", "bad/SKILL.md", id="parser-error"),
        pytest.param(b"---\nname: other\ndescription: d\n---\n", "bad/SKILL.md", id="name-differs-from-directory"),
        pytest.param(b"---\nname: Bad_Name\ndescription: d\n---\n", "Bad_Name/SKILL.md", id="name-grammar"),
        pytest.param(b"---\nname: bad\ndescription:\n---\n", "bad/SKILL.md", id="empty-description"),
        pytest.param(b"---\nname: bad\n---\n", "bad/SKILL.md", id="missing-description"),
        pytest.param(b"\xff\xfe", "bad/SKILL.md", id="not-utf-8"),
        pytest.param(_skill_md("root"), "SKILL.md", id="skill-md-at-the-provider-root"),
    ],
)
async def test_an_invalid_skill_is_skipped_with_a_warning_when_not_strict(
    skill_md: bytes, path: str, caplog: pytest.LogCaptureFixture
) -> None:
    """SDK-defined (matches typescript-sdk #3047): invalid skills are skipped, the valid ones still served."""
    with caplog.at_level(logging.WARNING, logger=CATALOG_LOGGER):
        server = await _server({path: skill_md, "good/SKILL.md": _skill_md("good")})
    async with Client(server, extensions=[ClientSkills()]) as client:
        skills = await client.extension(ClientSkills).list_skills()

    assert [skill.uri for skill in skills] == ["skill://good/SKILL.md"]
    assert [record.getMessage() for record in caplog.records if path in record.getMessage()] != []


async def test_a_non_mapping_frontmatter_result_makes_the_skill_invalid() -> None:
    """SDK-defined: the injected parser must return a mapping with string keys."""

    def parse_to_list(text: str) -> Any:
        return ["not", "a", "mapping"]

    provider = _MemoryProvider({"bad/SKILL.md": _skill_md("bad")})
    with pytest.raises(ValueError) as exc_info:
        await SkillCatalog.load(provider, parse_frontmatter=parse_to_list, strict=True)
    assert "bad/SKILL.md" in str(exc_info.value)


async def test_a_frontmatter_mapping_with_non_string_keys_makes_the_skill_invalid() -> None:
    """SDK-defined: frontmatter is rendered as JSON, so its keys must be strings."""

    def parse_with_int_key(text: str) -> Mapping[Any, Any]:
        return {1: "one"}

    provider = _MemoryProvider({"bad/SKILL.md": _skill_md("bad")})
    with pytest.raises(ValueError) as exc_info:
        await SkillCatalog.load(provider, parse_frontmatter=parse_with_int_key, strict=True)
    assert "bad/SKILL.md" in str(exc_info.value)


async def test_a_frontmatter_value_that_is_not_json_serializable_makes_the_skill_invalid() -> None:
    """SDK-defined: frontmatter must be representable as JSON on the wire."""

    def parse_with_unserializable(text: str) -> Mapping[str, Any]:
        return {"name": "bad", "description": "d", "broken": float("nan"), "key": object()}

    provider = _MemoryProvider({"bad/SKILL.md": _skill_md("bad")})
    with pytest.raises(ValueError) as exc_info:
        await SkillCatalog.load(provider, parse_frontmatter=parse_with_unserializable, strict=True)
    assert "bad/SKILL.md" in str(exc_info.value)


async def test_a_frontmatter_value_with_no_json_form_makes_the_skill_invalid() -> None:
    """SDK-defined: NaN can't be carried verbatim as JSON, so it is rejected instead of being silently rewritten."""

    def parse_with_nan(text: str) -> Mapping[str, Any]:
        return {"name": "bad", "description": "d", "ratio": float("nan")}

    provider = _MemoryProvider({"bad/SKILL.md": _skill_md("bad")})
    with pytest.raises(ValueError) as exc_info:
        await SkillCatalog.load(provider, parse_frontmatter=parse_with_nan, strict=True)
    assert "bad/SKILL.md" in str(exc_info.value)


async def test_a_provider_may_return_any_iterable_of_paths() -> None:
    """SDK-defined: the listing is consumed once, so a generator doesn't silently yield an empty catalog."""

    class GeneratorProvider(_MemoryProvider):
        async def list_files(self) -> Sequence[str]:
            return cast(Sequence[str], (path for path in self.files))

    catalog = await SkillCatalog.load(
        GeneratorProvider({"git-workflow/SKILL.md": _skill_md("git-workflow")}), parse_frontmatter=_parse
    )
    assert [skill.uri for skill in await _listed(catalog)] == ["skill://git-workflow/SKILL.md"]


async def test_strict_load_raises_one_error_naming_every_invalid_skill() -> None:
    """SDK-defined (matches typescript-sdk #3047 `strict`): all problems are reported together."""
    provider = _MemoryProvider(
        {
            "first/SKILL.md": b"no frontmatter",
            "second/SKILL.md": _skill_md("mismatch"),
            "good/SKILL.md": _skill_md("good"),
        }
    )
    with pytest.raises(ValueError) as exc_info:
        await SkillCatalog.load(provider, parse_frontmatter=_parse, strict=True)
    message = str(exc_info.value)
    assert "first/SKILL.md" in message
    assert "second/SKILL.md" in message
    assert "good/SKILL.md" not in message


@pytest.mark.parametrize(
    "listing",
    [
        pytest.param([""], id="empty"),
        pytest.param(["/abs/SKILL.md"], id="absolute"),
        pytest.param(["a/./SKILL.md"], id="dot-segment"),
        pytest.param(["a/../SKILL.md"], id="dot-dot-segment"),
        pytest.param(["a//SKILL.md"], id="empty-segment"),
        pytest.param(["a/SKILL.md", "a/SKILL.md"], id="duplicate"),
        pytest.param(["a/SKILL.md", "a/notes", "a/notes/more.txt"], id="file-beneath-a-file"),
    ],
)
async def test_a_provider_listing_a_malformed_path_is_a_value_error_even_when_not_strict(
    listing: list[str],
) -> None:
    """SDK-defined: a malformed listing is a provider bug, not an invalid skill, so it never degrades to a warning."""
    provider = _MemoryProvider({"a/SKILL.md": _skill_md("a")}, listing=listing)
    with pytest.raises(ValueError):
        await SkillCatalog.load(provider, parse_frontmatter=_parse)


async def test_a_provider_error_while_loading_propagates() -> None:
    """SDK-defined: only skill invalidity is tolerated; a provider that fails to read aborts the load."""
    provider = _MemoryProvider({}, listing=["a/SKILL.md"])
    with pytest.raises(KeyError):
        await SkillCatalog.load(provider, parse_frontmatter=_parse)


async def test_frontmatter_passes_through_verbatim_and_dates_become_iso_strings() -> None:
    """SEP-2640: the listing carries the frontmatter verbatim, as JSON; unknown keys survive (ext-skills#126)."""

    def parse_with_date(text: str) -> Mapping[str, Any]:
        return {
            "name": "git-workflow",
            "description": "d",
            "released": datetime.date(2026, 7, 28),
            "x-custom": {"nested": [1, 2]},
        }

    catalog = await SkillCatalog.load(
        _MemoryProvider({"git-workflow/SKILL.md": _skill_md("git-workflow")}), parse_frontmatter=parse_with_date
    )
    assert (await _listed(catalog))[0].frontmatter == {
        "name": "git-workflow",
        "description": "d",
        "released": "2026-07-28",
        "x-custom": {"nested": [1, 2]},
    }


async def test_files_are_served_byte_exact_including_bom_and_crlf() -> None:
    """SEP-2640: `resources/read` returns the same bytes the manifest digest describes."""
    skill_md = b"\xef\xbb\xbf---\r\nname: git-workflow\r\ndescription: d\r\n---\r\nBody\r\n"
    server = await _server({"git-workflow/SKILL.md": skill_md})
    async with Client(server, extensions=[ClientSkills()]) as client:
        skill = (await client.extension(ClientSkills).list_skills())[0]
        contents = (await client.read_resource("skill://git-workflow/SKILL.md")).contents[0]

    assert isinstance(contents, TextResourceContents)
    assert contents.text.encode("utf-8") == skill_md
    assert isinstance(skill.resources, list)
    assert skill.resources[0].digest == _digest(skill_md)


async def test_a_file_that_is_not_utf_8_is_served_as_a_blob() -> None:
    """SDK-defined: content that can't be text is returned as a base64 blob, byte-exact."""
    binary = bytes(range(256))
    server = await _server({"git-workflow/SKILL.md": _skill_md("git-workflow"), "git-workflow/assets/data.bin": binary})
    async with Client(server) as client:
        contents = (await client.read_resource("skill://git-workflow/assets/data.bin")).contents[0]

    assert isinstance(contents, BlobResourceContents)
    assert base64.b64decode(contents.blob) == binary
    assert contents.mime_type == "application/octet-stream"


async def test_skill_md_is_served_as_markdown_with_its_own_name_and_description() -> None:
    """SEP-2640: `SKILL.md` is `text/markdown`; other files carry their own type, or a generic one."""
    server = await _server(
        {
            "git-workflow/SKILL.md": _skill_md("git-workflow", description="Follow our Git rules"),
            "git-workflow/notes.json": b"{}",
            "git-workflow/references/GUIDE.MD": b"# Guide",
            "git-workflow/blob.unknownext": b"x",
            "git-workflow/no-extension": b"x",
        }
    )
    async with Client(server) as client:
        listed = {resource.uri: resource for resource in (await client.list_resources()).resources}

    skill_md = listed["skill://git-workflow/SKILL.md"]
    assert (skill_md.name, skill_md.description, skill_md.mime_type) == (
        "git-workflow",
        "Follow our Git rules",
        "text/markdown",
    )
    assert listed["skill://git-workflow/notes.json"].name == "notes.json"
    assert listed["skill://git-workflow/notes.json"].mime_type == "application/json"
    assert listed["skill://git-workflow/references/GUIDE.MD"].mime_type == "text/markdown"
    assert listed["skill://git-workflow/blob.unknownext"].mime_type == "application/octet-stream"
    assert listed["skill://git-workflow/no-extension"].mime_type == "application/octet-stream"


async def test_reading_a_file_that_changed_after_load_is_an_internal_error() -> None:
    """SDK-defined: the served bytes must match the manifest digest, so drift fails the read."""
    provider = _MemoryProvider({"git-workflow/SKILL.md": _skill_md("git-workflow")})
    catalog = await SkillCatalog.load(provider, parse_frontmatter=_parse)
    provider.files["git-workflow/SKILL.md"] = _skill_md("git-workflow", description="tampered")
    async with Client(MCPServer("skills", extensions=[catalog])) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("skill://git-workflow/SKILL.md")
    assert exc_info.value.code == INTERNAL_ERROR


async def test_reading_a_uri_outside_the_catalog_is_invalid_params() -> None:
    """SEP-2640: only listed files are served; the lookup is an exact URI match."""
    server = await _server({"git-workflow/SKILL.md": _skill_md("git-workflow")})
    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("skill://git-workflow/../git-workflow/SKILL.md")
    assert exc_info.value.code == INVALID_PARAMS


async def test_special_characters_in_a_path_are_percent_encoded_and_still_readable() -> None:
    """SEP-2640 Resource Mapping: URIs must be valid, so a space or `#` in a file name is percent-encoded."""
    server = await _server(
        {"git-workflow/SKILL.md": _skill_md("git-workflow"), "git-workflow/my notes #1.md": b"notes"}
    )
    async with Client(server, extensions=[ClientSkills()]) as client:
        skill = (await client.extension(ClientSkills).list_skills())[0]
        contents = (await client.read_resource("skill://git-workflow/my%20notes%20%231.md")).contents[0]

    assert isinstance(skill.resources, list)
    assert "skill://git-workflow/my%20notes%20%231.md" in [r.uri for r in skill.resources]
    assert isinstance(contents, TextResourceContents)
    assert contents.text == "notes"


async def test_a_skill_over_the_recommended_limits_is_still_served_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SEP-2640: 512 files and 16 MiB are SHOULD NOT limits, so the skill is served and the overage is logged."""
    files = {"big/SKILL.md": _skill_md("big"), "big/huge.bin": bytes(MAX_TOTAL_SIZE)}
    files.update({f"big/f{i}.txt": b"x" for i in range(MAX_RESOURCES_PER_SKILL)})
    with caplog.at_level(logging.WARNING, logger=CATALOG_LOGGER):
        catalog = await SkillCatalog.load(_MemoryProvider(files), parse_frontmatter=_parse)

    assert [skill.uri for skill in await _listed(catalog)] == ["skill://big/SKILL.md"]
    assert len([record for record in caplog.records if "skill://big/SKILL.md" in record.getMessage()]) == 2


async def test_directory_read_is_neither_advertised_nor_registered_by_default() -> None:
    """SEP-2640: `directoryRead` is opt-in; without it the capability is empty and the method absent."""
    server = await _server({"git-workflow/SKILL.md": _skill_md("git-workflow")})
    async with Client(server) as client:
        assert client.server_capabilities.extensions == {"io.modelcontextprotocol/skills": {}}
        with pytest.raises(MCPError):
            await client.session.send_request(
                ReadDirectoryRequest(params=ReadDirectoryParams(uri="skill://git-workflow")), ReadDirectoryResult
            )


async def test_directory_read_lists_direct_children_at_every_level() -> None:
    """SEP-2640 Directory resources: each directory lists its direct children, including organisation levels."""
    server = await _server(
        {
            "acme/billing/SKILL.md": _skill_md("billing"),
            "acme/billing/references/guide.txt": b"guide",
            "acme/billing/references/deep/more.txt": b"more",
            "acme/billing/.git/config": b"hidden",
        },
        directory_read=True,
    )

    async def children(client: Client, uri: str) -> list[tuple[str, str | None]]:
        return [(r.uri, r.mime_type) for r in await client.extension(ClientSkills).read_directory(uri)]

    async with Client(server, extensions=[ClientSkills()]) as client:
        assert client.server_capabilities.extensions == {"io.modelcontextprotocol/skills": {"directoryRead": True}}
        assert await children(client, "skill://acme") == [("skill://acme/billing", "inode/directory")]
        assert await children(client, "skill://acme/billing") == [
            ("skill://acme/billing/SKILL.md", "text/markdown"),
            ("skill://acme/billing/references", "inode/directory"),
        ]
        assert await children(client, "skill://acme/billing/references") == [
            ("skill://acme/billing/references/deep", "inode/directory"),
            ("skill://acme/billing/references/guide.txt", "text/plain"),
        ]
        names = {r.uri: r.name for r in await client.extension(ClientSkills).read_directory("skill://acme/billing")}

    assert names["skill://acme/billing/references"] == "references"


@pytest.mark.parametrize(
    "uri",
    [
        pytest.param("skill://acme/unknown", id="unknown-directory"),
        pytest.param("skill://acme/billing/SKILL.md", id="file"),
        pytest.param("skill://acme/billing/.git", id="hidden-directory"),
    ],
)
async def test_directory_read_of_anything_but_a_served_directory_is_invalid_params(uri: str) -> None:
    """SDK-defined: only directories holding served files can be read."""
    server = await _server(
        {"acme/billing/SKILL.md": _skill_md("billing"), "acme/billing/.git/config": b"hidden"}, directory_read=True
    )
    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(
                ReadDirectoryRequest(params=ReadDirectoryParams(uri=uri)), ReadDirectoryResult
            )
    assert exc_info.value.code == INVALID_PARAMS


async def test_directory_read_rejects_a_cursor() -> None:
    """SDK-defined: the catalog answers on a single page, so any cursor is Invalid params."""
    server = await _server({"acme/billing/SKILL.md": _skill_md("billing")}, directory_read=True)
    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(
                ReadDirectoryRequest(params=ReadDirectoryParams(uri="skill://acme", cursor="page-2")),
                ReadDirectoryResult,
            )
    assert exc_info.value.code == INVALID_PARAMS


async def test_cache_hints_reach_list_get_and_directory_reads_on_the_2026_07_28_wire() -> None:
    """SEP-2549: the configured `ttl_ms`/`cache_scope` are sent on every catalog result."""
    server = await _server(
        {"git-workflow/SKILL.md": _skill_md("git-workflow")}, directory_read=True, ttl_ms=60_000, cache_scope="public"
    )
    async with Client(server, mode="2026-07-28") as client:
        raws = [
            await client.session.send_request(ListSkillsRequest(), _RawResult),
            await client.session.send_request(
                GetSkillRequest(params=GetSkillParams(uri="skill://git-workflow/SKILL.md")), _RawResult
            ),
            await client.session.send_request(
                ReadDirectoryRequest(params=ReadDirectoryParams(uri="skill://git-workflow")), _RawResult
            ),
        ]
    assert [(raw.model_extra or {})["ttlMs"] for raw in raws] == [60_000] * 3
    assert [(raw.model_extra or {})["cacheScope"] for raw in raws] == ["public"] * 3


def _five_skills() -> dict[str, bytes]:
    return {f"skill-{n}/SKILL.md": _skill_md(f"skill-{n}") for n in range(5)}


async def test_list_skills_pages_through_the_catalog_when_a_page_size_is_set() -> None:
    """SEP-2640: `skills/list` mirrors base-protocol pagination; each `nextCursor` is passed back as `cursor`."""
    server = await _server(_five_skills(), page_size=2)
    async with Client(server) as client:
        first = await client.session.send_request(ListSkillsRequest(), ListSkillsResult)
        second = await client.session.send_request(
            ListSkillsRequest(params=ListSkillsParams(cursor=first.next_cursor)), ListSkillsResult
        )
        assert second.next_cursor is not None
        third = await client.session.send_request(
            ListSkillsRequest(params=ListSkillsParams(cursor=second.next_cursor)), ListSkillsResult
        )

    pages = [[skill.uri for skill in page.skills] for page in (first, second, third)]
    assert pages == [
        ["skill://skill-0/SKILL.md", "skill://skill-1/SKILL.md"],
        ["skill://skill-2/SKILL.md", "skill://skill-3/SKILL.md"],
        ["skill://skill-4/SKILL.md"],
    ]
    assert first.next_cursor is not None
    assert third.next_cursor is None


async def test_the_client_follows_next_cursor_to_collect_every_skill_with_whole_entries() -> None:
    """SEP-2640: an entry is atomic, so a skill's manifest is complete on whichever page carries it."""
    files = {**_five_skills(), "skill-0/references/guide.md": b"guide", "skill-0/references/more.md": b"more"}
    server = await _server(files, page_size=2)
    async with Client(server, extensions=[ClientSkills()]) as client:
        skills = await client.extension(ClientSkills).list_skills()

    assert [skill.uri for skill in skills] == [f"skill://skill-{n}/SKILL.md" for n in range(5)]
    assert isinstance(skills[0].resources, list)
    assert len(skills[0].resources) == 3


async def test_a_page_size_larger_than_the_catalog_returns_one_page_without_a_cursor() -> None:
    """SDK-defined: `nextCursor` is only present when another page follows."""
    server = await _server(_five_skills(), page_size=5)
    async with Client(server) as client:
        result = await client.session.send_request(ListSkillsRequest(), ListSkillsResult)
    assert len(result.skills) == 5
    assert result.next_cursor is None


@pytest.mark.parametrize(
    "cursor",
    [
        pytest.param("not base64 !", id="not-base64"),
        pytest.param("\u00e9", id="not-ascii"),
        pytest.param("", id="empty"),
        pytest.param(base64.urlsafe_b64encode(b"abc").decode(), id="not-a-number"),
        pytest.param(base64.urlsafe_b64encode(b"0").decode(), id="zero"),
        pytest.param(base64.urlsafe_b64encode(b"3").decode(), id="not-a-page-boundary"),
        pytest.param(base64.urlsafe_b64encode(b"10").decode(), id="past-the-end"),
        pytest.param(base64.urlsafe_b64encode(b" 2").decode(), id="non-canonical"),
    ],
)
async def test_a_cursor_the_catalog_did_not_issue_is_invalid_params(cursor: str) -> None:
    """Base protocol: an invalid cursor is Invalid params (-32602)."""
    server = await _server(_five_skills(), page_size=2)
    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(
                ListSkillsRequest(params=ListSkillsParams(cursor=cursor)), ListSkillsResult
            )
    assert exc_info.value.code == INVALID_PARAMS


async def test_directory_read_pages_through_the_children_when_a_page_size_is_set() -> None:
    """SEP-2640: `resources/directory/read` mirrors `resources/list` pagination."""
    files = {"git-workflow/SKILL.md": _skill_md("git-workflow")}
    files.update({f"git-workflow/references/f{n}.txt": b"x" for n in range(5)})
    server = await _server(files, directory_read=True, page_size=2)
    async with Client(server, extensions=[ClientSkills()]) as client:
        first = await client.session.send_request(
            ReadDirectoryRequest(params=ReadDirectoryParams(uri="skill://git-workflow/references")),
            ReadDirectoryResult,
        )
        everything = await client.extension(ClientSkills).read_directory("skill://git-workflow/references")
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(
                ReadDirectoryRequest(params=ReadDirectoryParams(uri="skill://git-workflow/references", cursor="bogus")),
                ReadDirectoryResult,
            )

    assert len(first.resources) == 2
    assert first.next_cursor is not None
    assert [r.uri for r in everything] == [f"skill://git-workflow/references/f{n}.txt" for n in range(5)]
    assert exc_info.value.code == INVALID_PARAMS


@pytest.mark.parametrize("page_size", [0, -1])
async def test_a_page_size_below_one_is_rejected_when_the_catalog_loads(page_size: int) -> None:
    """SDK-defined: a page must hold at least one entry."""
    provider = _MemoryProvider({"git-workflow/SKILL.md": _skill_md("git-workflow")})
    with pytest.raises(ValueError):
        await SkillCatalog.load(provider, parse_frontmatter=_parse, page_size=page_size)


async def test_a_negative_ttl_is_rejected_before_the_provider_is_used() -> None:
    """SEP-2549: `ttlMs` is non-negative, and a bad option fails at load before the provider is scanned.

    The provider has no methods, so reaching it would raise `AttributeError` instead of `ValueError`.
    """
    provider = cast(SkillProvider, object())
    with pytest.raises(ValueError):
        await SkillCatalog.load(provider, parse_frontmatter=_parse, ttl_ms=-1)


async def test_load_returns_an_instance_of_the_subclass_it_is_called_on() -> None:
    """SDK-defined: `load()` is a classmethod constructor, so a subclass gets its own type back."""

    class _CustomCatalog(SkillCatalog):
        pass

    provider = _MemoryProvider({"git-workflow/SKILL.md": _skill_md("git-workflow")})
    catalog = await _CustomCatalog.load(provider, parse_frontmatter=_parse)

    assert isinstance(catalog, _CustomCatalog)


async def test_the_handler_aliases_stay_importable_from_the_package() -> None:
    """Compatibility: `mcp.server.skills` was a module before it became a package; its public names survive."""
    assert (GetSkillHandler, ListSkillsHandler, ReadDirectoryHandler) == (
        skills_package.GetSkillHandler,
        skills_package.ListSkillsHandler,
        skills_package.ReadDirectoryHandler,
    )
    assert skills_package.__all__ == ["Skills", "SkillCatalog", "SkillProvider", "FilesystemSkillProvider"]


async def test_cache_hints_default_to_a_private_zero_ttl() -> None:
    """SEP-2549: with no options set, results carry the `CacheableResult` defaults."""
    server = await _server({"git-workflow/SKILL.md": _skill_md("git-workflow")})
    async with Client(server, mode="2026-07-28") as client:
        raw = await client.session.send_request(ListSkillsRequest(), _RawResult)
    extra = raw.model_extra or {}
    assert (extra["ttlMs"], extra["cacheScope"]) == (0, "private")


async def test_cache_hints_are_omitted_on_a_legacy_wire() -> None:
    """SEP-2549 fields are 2026-07-28+ only; `Skills` strips them for an older connection."""
    server = await _server({"git-workflow/SKILL.md": _skill_md("git-workflow")}, ttl_ms=60_000, cache_scope="public")
    async with Client(server, mode="legacy") as client:
        raw = await client.session.send_request(ListSkillsRequest(), _RawResult)
    extra = raw.model_extra or {}
    assert "ttlMs" not in extra
    assert "cacheScope" not in extra


async def test_a_catalog_over_a_directory_serves_files_whose_bytes_match_the_manifest(tmp_path: Path) -> None:
    """End to end over `FilesystemSkillProvider`: list, get, directory read and read agree with the disk."""
    skill_dir = tmp_path / "git-workflow"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_bytes(_skill_md("git-workflow"))
    (skill_dir / "references" / "conventions.md").write_bytes(b"# Conventions\n")
    (skill_dir / "references" / "logo.png").write_bytes(b"\x89PNG\xff\x00")

    catalog = await SkillCatalog.load(FilesystemSkillProvider(tmp_path), parse_frontmatter=_parse, directory_read=True)
    async with Client(MCPServer("skills", extensions=[catalog]), extensions=[ClientSkills()]) as client:
        skills_client = client.extension(ClientSkills)
        listed = (await skills_client.list_skills())[0]
        assert await skills_client.get_skill(listed.uri) == listed
        children = await skills_client.read_directory("skill://git-workflow/references")
        assert [r.uri for r in children] == [
            "skill://git-workflow/references/conventions.md",
            "skill://git-workflow/references/logo.png",
        ]
        assert isinstance(listed.resources, list)
        for entry in listed.resources:
            contents = (await client.read_resource(entry.uri)).contents[0]
            if isinstance(contents, BlobResourceContents):
                data = base64.b64decode(contents.blob)
            else:
                assert isinstance(contents, TextResourceContents)
                data = contents.text.encode("utf-8")
            assert (_digest(data), len(data)) == (entry.digest, entry.size)
