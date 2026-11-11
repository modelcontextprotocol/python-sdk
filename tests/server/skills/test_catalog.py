"""Tests for `SkillCatalog` (`mcp.server.skills.catalog`): the provider-backed Skills extension.

Protocol behavior is exercised through an in-memory `Client`; provider validation is also tested
directly. The provider is a dict of bytes and the parser a `key: value` stand-in, so these tests
don't need a YAML dependency.
"""

import base64
import datetime
import hashlib
import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, cast

import anyio
import pytest
from anyio.streams.memory import MemoryObjectReceiveStream
from inline_snapshot import snapshot
from mcp_types import INTERNAL_ERROR, INVALID_PARAMS, BlobResourceContents, Resource, TextResourceContents
from pydantic import BaseModel, ConfigDict

import mcp.server.skills as skills_package
import mcp.server.skills.catalog as catalog_module
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
    SkillResource,
)
from tests.interaction._connect import Connect, connect_over_sse, connect_over_streamable_http

pytestmark = pytest.mark.anyio

CATALOG_LOGGER = "mcp.server.skills.catalog"
SERVER_LOGGER = "mcp.server.mcpserver.server"


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

    assert skills == snapshot(
        [
            Skill(
                uri="skill://git-workflow/SKILL.md",
                frontmatter={"name": "git-workflow", "description": "Does the thing"},
                resources=[
                    SkillResource(
                        uri="skill://git-workflow/SKILL.md",
                        digest="sha256:d22b532ae94dfd7cc7de74d2bac0b7ab49fc828f5ba0d8dbdf09a2a2e742fb56",
                        size=78,
                    ),
                    SkillResource(
                        uri="skill://git-workflow/references/conventions.md",
                        digest="sha256:49ff9bdae2e9b1ed9344b60816f5a8fe12de9c83b4500445d14efb780d57f2fe",
                        size=14,
                    ),
                ],
            ),
            Skill(
                uri="skill://zebra/SKILL.md",
                frontmatter={"name": "zebra", "description": "Does the thing"},
                resources=[
                    SkillResource(
                        uri="skill://zebra/SKILL.md",
                        digest="sha256:144b1db8b322f52937e68c92ba7d87bf8b1e3f8196cbdeda66ce5e40371ee2c2",
                        size=64,
                    )
                ],
            ),
        ]
    )


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
    assert (await _listed(catalog))[0].frontmatter == snapshot(
        {"name": "git-workflow", "description": "d", "released": "2026-07-28", "x-custom": {"nested": [1, 2]}}
    )


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

    assert listed == snapshot(
        {
            "skill://git-workflow/SKILL.md": Resource(
                name="git-workflow",
                uri="skill://git-workflow/SKILL.md",
                description="Follow our Git rules",
                mime_type="text/markdown",
            ),
            "skill://git-workflow/blob.unknownext": Resource(
                name="blob.unknownext", uri="skill://git-workflow/blob.unknownext", mime_type="application/octet-stream"
            ),
            "skill://git-workflow/no-extension": Resource(
                name="no-extension", uri="skill://git-workflow/no-extension", mime_type="application/octet-stream"
            ),
            "skill://git-workflow/notes.json": Resource(
                name="notes.json", uri="skill://git-workflow/notes.json", mime_type="application/json"
            ),
            "skill://git-workflow/references/GUIDE.MD": Resource(
                name="GUIDE.MD", uri="skill://git-workflow/references/GUIDE.MD", mime_type="text/markdown"
            ),
        }
    )


async def test_reading_a_file_that_changed_after_load_is_an_internal_error() -> None:
    """SDK-defined: the served bytes must match the manifest digest, so drift fails the read."""
    provider = _MemoryProvider({"git-workflow/SKILL.md": _skill_md("git-workflow")})
    catalog = await SkillCatalog.load(provider, parse_frontmatter=_parse)
    provider.files["git-workflow/SKILL.md"] = _skill_md("git-workflow", description="tampered")
    async with Client(MCPServer("skills", extensions=[catalog])) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("skill://git-workflow/SKILL.md")
    assert exc_info.value.code == INTERNAL_ERROR
    assert exc_info.value.message == "skill://git-workflow/SKILL.md changed after the last scan"


async def test_reading_a_file_deleted_after_load_is_an_internal_error_without_a_traceback(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """SDK-defined: a file removed before the next reload is an expected state, logged as a failed read, not a crash."""
    (tmp_path / "git-workflow").mkdir()
    (tmp_path / "git-workflow" / "SKILL.md").write_bytes(_skill_md("git-workflow"))
    (tmp_path / "git-workflow" / "guide.md").write_bytes(b"# Guide\n")
    catalog = await SkillCatalog.load(FilesystemSkillProvider(tmp_path), parse_frontmatter=_parse)
    (tmp_path / "git-workflow" / "guide.md").unlink()
    caplog.set_level(logging.INFO, logger=SERVER_LOGGER)

    async with Client(MCPServer("skills", extensions=[catalog])) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("skill://git-workflow/guide.md")

    assert exc_info.value.code == INTERNAL_ERROR
    assert (
        exc_info.value.message
        == "skill://git-workflow/guide.md could not be read; it was deleted or became unreadable after the last scan"
    )
    records = [record for record in caplog.records if record.name == SERVER_LOGGER]
    assert [(record.levelno, record.exc_info) for record in records] == [(logging.INFO, None)]


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
async def test_a_malformed_misaligned_or_out_of_range_cursor_is_invalid_params(cursor: str) -> None:
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


async def _reloadable(files: Mapping[str, bytes], **options: Any) -> tuple[_MemoryProvider, SkillCatalog, MCPServer]:
    provider = _MemoryProvider(files)
    catalog = await SkillCatalog.load(provider, parse_frontmatter=_parse, **options)
    return provider, catalog, MCPServer("skills", extensions=[catalog])


@pytest.fixture
async def refresh_timer(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[MemoryObjectReceiveStream[tuple[float, anyio.Event]], anyio.Event]]:
    """Control interval boundaries without waiting for wall-clock time."""
    send, receive = anyio.create_memory_object_stream[tuple[float, anyio.Event]](1)
    cancelled = anyio.Event()

    async def wait(seconds: float) -> None:
        gate = anyio.Event()
        try:
            await send.send((seconds, gate))
            await gate.wait()
        except anyio.get_cancelled_exc_class():
            cancelled.set()
            raise

    monkeypatch.setattr(catalog_module, "sleep", wait)
    async with send, receive:
        yield receive, cancelled


@pytest.mark.parametrize("interval", [0, -1, float("nan"), float("inf"), -float("inf")])
async def test_refresh_rejects_intervals_that_are_not_finite_and_positive(interval: float) -> None:
    """SDK-defined: the refresh interval is positive finite seconds, whether or not refreshing is enabled."""
    with pytest.raises(ValueError) as exc_info:
        await SkillCatalog.load(_MemoryProvider({}), parse_frontmatter=_parse, refresh_interval=interval)
    assert str(exc_info.value) == "refresh_interval must be finite and greater than zero"


async def test_refresh_is_off_by_default(
    refresh_timer: tuple[MemoryObjectReceiveStream[tuple[float, anyio.Event]], anyio.Event],
) -> None:
    """SDK-defined: without `auto_refresh` the catalog changes only when `reload()` is called."""
    ticks, _ = refresh_timer
    provider, _, server = await _reloadable({"git-workflow/SKILL.md": _skill_md("git-workflow")})
    provider.files["git-workflow/SKILL.md"] = _skill_md("git-workflow", "Edited")
    async with Client(server, extensions=[ClientSkills()]) as client:
        await anyio.wait_all_tasks_blocked()
        with pytest.raises(anyio.WouldBlock):
            ticks.receive_nowait()
        assert (await client.extension(ClientSkills).list_skills())[0].frontmatter["description"] == "Does the thing"


async def test_refresh_interval_defaults_to_sixty_seconds_once_enabled(
    refresh_timer: tuple[MemoryObjectReceiveStream[tuple[float, anyio.Event]], anyio.Event],
) -> None:
    """SDK-defined: `auto_refresh=True` alone is enough; `refresh_interval` only overrides the default."""
    ticks, _ = refresh_timer
    _, _, server = await _reloadable({"git-workflow/SKILL.md": _skill_md("git-workflow")}, auto_refresh=True)
    with anyio.fail_after(5):
        async with Client(server):
            seconds, _ = await ticks.receive()
            assert seconds == 60.0


async def test_refresh_atomically_replaces_skills_resources_and_directories() -> None:
    """SDK-defined: requests serve the old snapshot during a rescan, then all surfaces switch together."""
    ready, publish, finished = anyio.Event(), anyio.Event(), anyio.Event()

    class GatedProvider(_MemoryProvider):
        block = False

        async def read_file(self, path: str) -> bytes:
            if self.block and path == "new/SKILL.md":
                ready.set()
                await publish.wait()
            return await super().read_file(path)

    old_md = _skill_md("old")
    provider = GatedProvider({"old/SKILL.md": old_md, "keep/SKILL.md": _skill_md("keep")})
    catalog = await SkillCatalog.load(
        provider, parse_frontmatter=_parse, directory_read=True, page_size=1, auto_refresh=True, refresh_interval=3600
    )
    server = MCPServer("skills", extensions=[catalog])
    changes: list[catalog_module.SkillCatalogChanges] = []

    async def reload() -> None:
        changes.append(await catalog.reload())
        finished.set()

    with anyio.fail_after(5):
        async with Client(server, extensions=[ClientSkills()]) as client, anyio.create_task_group() as tasks:
            before = await client.extension(ClientSkills).list_skills()
            provider.files = {
                "keep/SKILL.md": _skill_md("keep", "Updated"),
                "new/SKILL.md": _skill_md("new"),
                "new/asset.bin": b"\xff\x00",
            }
            provider.block = True
            tasks.start_soon(reload)
            await ready.wait()
            assert await client.extension(ClientSkills).list_skills() == before
            assert await client.extension(ClientSkills).get_skill("skill://old/SKILL.md") == before[1]
            contents = (await client.read_resource("skill://old/SKILL.md")).contents[0]
            assert isinstance(contents, TextResourceContents)
            assert contents.text.encode("utf-8") == old_md
            assert [r.uri for r in (await client.list_resources()).resources] == [
                "skill://keep/SKILL.md",
                "skill://old/SKILL.md",
            ]

            publish.set()
            await finished.wait()
            listed = await client.extension(ClientSkills).list_skills()
            assert [skill.uri for skill in listed] == ["skill://keep/SKILL.md", "skill://new/SKILL.md"]
            assert listed[0].frontmatter["description"] == "Updated"
            assert await client.extension(ClientSkills).get_skill(listed[1].uri) == listed[1]
            assert [r.uri for r in (await client.list_resources()).resources] == [
                "skill://keep/SKILL.md",
                "skill://new/SKILL.md",
                "skill://new/asset.bin",
            ]
            assert [r.uri for r in await client.extension(ClientSkills).read_directory("skill://new")] == [
                "skill://new/SKILL.md",
                "skill://new/asset.bin",
            ]
            assert isinstance(listed[1].resources, list)
            for entry in listed[1].resources:
                content = (await client.read_resource(entry.uri)).contents[0]
                if isinstance(content, BlobResourceContents):
                    data = base64.b64decode(content.blob)
                else:
                    assert isinstance(content, TextResourceContents)
                    data = content.text.encode("utf-8")
                assert (_digest(data), len(data)) == (entry.digest, entry.size)
            with pytest.raises(MCPError) as exc_info:
                await client.read_resource("skill://old/SKILL.md")
            assert exc_info.value.code == INVALID_PARAMS
            with pytest.raises(MCPError) as directory_error:
                await client.extension(ClientSkills).read_directory("skill://old")
            assert directory_error.value.code == INVALID_PARAMS
            assert changes == [
                catalog_module.SkillCatalogChanges(
                    added=("skill://new/SKILL.md",),
                    removed=("skill://old/SKILL.md",),
                    changed=("skill://keep/SKILL.md",),
                )
            ]


async def test_a_failed_reload_leaves_the_previous_catalog_and_its_bytes_serving() -> None:
    """SDK-defined: one invalid skill rejects the whole replacement, including valid skills added beside it."""
    old_md = _skill_md("git-workflow")
    provider, catalog, server = await _reloadable({"git-workflow/SKILL.md": old_md}, auto_refresh=True, strict=True)
    provider.files["git-workflow/SKILL.md"] = b"not frontmatter"
    provider.files["new/SKILL.md"] = _skill_md("new")
    async with Client(server, extensions=[ClientSkills()]) as client:
        before = await client.extension(ClientSkills).list_skills()
        with pytest.raises(ValueError):
            await catalog.reload()
        assert await client.extension(ClientSkills).list_skills() == before
        contents = (await client.read_resource("skill://git-workflow/SKILL.md")).contents[0]
        assert isinstance(contents, TextResourceContents)
        assert contents.text.encode("utf-8") == old_md


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_periodic_refresh_publishes_disk_edits_and_stops_on_shutdown(
    tmp_path: Path,
    mode: Literal["legacy", "auto"],
    refresh_timer: tuple[MemoryObjectReceiveStream[tuple[float, anyio.Event]], anyio.Event],
) -> None:
    """SDK-defined: the configured timer reloads actual files on both wires and is cancelled at shutdown."""
    ticks, cancelled = refresh_timer
    skill_dir = tmp_path / "git-workflow"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_bytes(_skill_md("git-workflow"))
    catalog = await SkillCatalog.load(
        FilesystemSkillProvider(tmp_path), parse_frontmatter=_parse, auto_refresh=True, refresh_interval=0.25
    )
    with anyio.fail_after(5):
        async with Client(MCPServer("skills", extensions=[catalog]), mode=mode, extensions=[ClientSkills()]) as client:
            seconds, tick = await ticks.receive()
            assert seconds == 0.25
            (skill_dir / "SKILL.md").write_bytes(_skill_md("git-workflow", "Reloaded"))
            tick.set()
            await ticks.receive()
            listed = await client.extension(ClientSkills).list_skills()
            assert listed[0].frontmatter["description"] == "Reloaded"
            contents = (await client.read_resource(listed[0].uri)).contents[0]
            assert isinstance(contents, TextResourceContents)
            assert contents.text.encode("utf-8") == _skill_md("git-workflow", "Reloaded")
        assert cancelled.is_set()


@pytest.mark.parametrize("connect", [connect_over_sse, connect_over_streamable_http])
async def test_periodic_refresh_runs_and_shuts_down_with_network_transport_lifespans(
    connect: Connect,
    refresh_timer: tuple[MemoryObjectReceiveStream[tuple[float, anyio.Event]], anyio.Event],
) -> None:
    """SDK-defined: SSE and streamable HTTP own and cancel the refresh worker, entirely in process."""
    ticks, cancelled = refresh_timer
    provider, _, server = await _reloadable(
        {"git-workflow/SKILL.md": _skill_md("git-workflow")}, auto_refresh=True, refresh_interval=1
    )
    with anyio.fail_after(5):
        async with connect(server, extensions=[ClientSkills()]) as client:
            _, tick = await ticks.receive()
            provider.files["git-workflow/SKILL.md"] = _skill_md("git-workflow", "Reloaded")
            tick.set()
            await ticks.receive()
            assert (await client.extension(ClientSkills).list_skills())[0].frontmatter["description"] == "Reloaded"
        assert cancelled.is_set()


async def test_refresh_worker_transfers_to_another_connection_when_the_first_closes(
    refresh_timer: tuple[MemoryObjectReceiveStream[tuple[float, anyio.Event]], anyio.Event],
) -> None:
    """SDK-defined: closing one per-connection lifespan does not stop refreshes for another live client."""
    ticks, _ = refresh_timer
    first_ready, close_first, first_closed = anyio.Event(), anyio.Event(), anyio.Event()
    provider, _, server = await _reloadable(
        {"git-workflow/SKILL.md": _skill_md("git-workflow")}, auto_refresh=True, refresh_interval=1
    )

    async def first_connection() -> None:
        async with Client(server, mode="legacy") as client:
            assert [r.uri for r in (await client.list_resources()).resources] == ["skill://git-workflow/SKILL.md"]
            first_ready.set()
            await close_first.wait()
        first_closed.set()

    async def second_connection() -> None:
        async with Client(server, mode="legacy", extensions=[ClientSkills()]) as client:
            close_first.set()
            await first_closed.wait()
            _, tick = await ticks.receive()
            provider.files["git-workflow/SKILL.md"] = _skill_md("git-workflow", "Second connection")
            tick.set()
            await ticks.receive()
            listed = await client.extension(ClientSkills).list_skills()
            assert listed[0].frontmatter["description"] == "Second connection"

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(first_connection)
            await first_ready.wait()
            await ticks.receive()
            tasks.start_soon(second_connection)


@pytest.mark.parametrize("failure", [OSError("unavailable"), RuntimeError("custom provider failure")])
async def test_periodic_refresh_logs_failures_keeps_serving_and_retries(
    failure: Exception,
    caplog: pytest.LogCaptureFixture,
    refresh_timer: tuple[MemoryObjectReceiveStream[tuple[float, anyio.Event]], anyio.Event],
) -> None:
    """SDK-defined: any background scan failure keeps the complete old snapshot and does not stop retries."""
    ticks, _ = refresh_timer

    class FailingProvider(_MemoryProvider):
        error: Exception | None = None

        async def list_files(self) -> Sequence[str]:
            if self.error is not None:
                raise self.error
            return await super().list_files()

    old_md = _skill_md("git-workflow")
    provider = FailingProvider({"git-workflow/SKILL.md": old_md})
    catalog = await SkillCatalog.load(provider, parse_frontmatter=_parse, auto_refresh=True, refresh_interval=1)
    with anyio.fail_after(5):
        async with Client(MCPServer("skills", extensions=[catalog]), extensions=[ClientSkills()]) as client:
            _, tick = await ticks.receive()
            before = await client.extension(ClientSkills).list_skills()
            provider.error = failure
            provider.files["git-workflow/SKILL.md"] = _skill_md("git-workflow", "Recovered")
            with caplog.at_level(logging.ERROR, logger=CATALOG_LOGGER):
                tick.set()
                _, retry = await ticks.receive()
            assert await client.extension(ClientSkills).list_skills() == before
            contents = (await client.read_resource(before[0].uri)).contents[0]
            assert isinstance(contents, TextResourceContents)
            assert contents.text.encode("utf-8") == old_md
            records = [record for record in caplog.records if record.name == CATALOG_LOGGER]
            assert len(records) == 1
            assert records[0].message == "Failed to refresh skills; continuing to serve the previous catalog"
            assert records[0].exc_info is not None
            assert records[0].exc_info[1] is failure
            provider.error = None
            retry.set()
            await ticks.receive()
            listed = await client.extension(ClientSkills).list_skills()
            assert listed[0].frontmatter["description"] == "Recovered"


async def test_reload_serves_an_edited_file_that_failed_to_read_before() -> None:
    """SDK-defined: a file edited after `load()` errors until `reload()`, then serves the new bytes and manifest."""
    guide = b"# Conventions\n"
    provider, catalog, server = await _reloadable(
        {"git-workflow/SKILL.md": _skill_md("git-workflow"), "git-workflow/guide.md": guide}
    )
    provider.files["git-workflow/guide.md"] = b"# Conventions, revised\n"
    async with Client(server, extensions=[ClientSkills()]) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("skill://git-workflow/guide.md")

        changes = await catalog.reload()

        skill = (await client.extension(ClientSkills).list_skills())[0]
        contents = (await client.read_resource("skill://git-workflow/guide.md")).contents[0]

    assert exc_info.value.code == INTERNAL_ERROR
    assert changes == catalog_module.SkillCatalogChanges(
        added=(), removed=(), changed=("skill://git-workflow/SKILL.md",)
    )
    assert isinstance(skill.resources, list)
    assert {r.uri: r.digest for r in skill.resources}["skill://git-workflow/guide.md"] == _digest(
        b"# Conventions, revised\n"
    )
    assert isinstance(contents, TextResourceContents)
    assert contents.text == "# Conventions, revised\n"


async def test_reload_publishes_edited_frontmatter_through_list_and_get() -> None:
    """SDK-defined: a changed `description` shows up in both `skills/list` and `skills/get` without a restart."""
    provider, catalog, server = await _reloadable({"git-workflow/SKILL.md": _skill_md("git-workflow")})
    provider.files["git-workflow/SKILL.md"] = _skill_md("git-workflow", description="Now with new rules")
    async with Client(server, extensions=[ClientSkills()]) as client:
        await catalog.reload()
        listed = (await client.extension(ClientSkills).list_skills())[0]
        fetched = await client.extension(ClientSkills).get_skill("skill://git-workflow/SKILL.md")

    assert listed.frontmatter["description"] == "Now with new rules"
    assert fetched.frontmatter["description"] == "Now with new rules"


async def test_reload_of_an_unchanged_provider_reports_no_changes() -> None:
    """SDK-defined: nothing edited means nothing reported."""
    _, catalog, _ = await _reloadable({"git-workflow/SKILL.md": _skill_md("git-workflow")})

    assert await catalog.reload() == catalog_module.SkillCatalogChanges(added=(), removed=(), changed=())


async def test_reload_updates_directory_listings() -> None:
    """SDK-defined: directory reads report the new size of an edited file."""
    provider, catalog, server = await _reloadable(
        {"git-workflow/SKILL.md": _skill_md("git-workflow"), "git-workflow/guide.md": b"short"}, directory_read=True
    )
    provider.files["git-workflow/guide.md"] = b"a much longer guide"
    async with Client(server, extensions=[ClientSkills()]) as client:
        await catalog.reload()
        children = await client.extension(ClientSkills).read_directory("skill://git-workflow")

    assert {str(child.uri): child.size for child in children}["skill://git-workflow/guide.md"] == len(
        b"a much longer guide"
    )


async def test_reload_picks_up_added_and_removed_skills_and_files_in_one_swap() -> None:
    """SDK-defined: a reload serves exactly what the provider holds now, with no per-skill bookkeeping."""
    provider, catalog, server = await _reloadable(
        {
            "old/SKILL.md": _skill_md("old"),
            "keep/SKILL.md": _skill_md("keep"),
            "keep/gone.md": b"gone",
        },
        directory_read=True,
    )
    provider.files = {
        "keep/SKILL.md": _skill_md("keep"),
        "keep/added.md": b"added",
        "new/SKILL.md": _skill_md("new"),
    }
    async with Client(server, extensions=[ClientSkills()]) as client:
        changes = await catalog.reload()
        listed = [skill.uri for skill in await client.extension(ClientSkills).list_skills()]
        resources = [r.uri for r in (await client.list_resources()).resources]
        added = (await client.read_resource("skill://keep/added.md")).contents[0]
        with pytest.raises(MCPError) as gone:
            await client.read_resource("skill://keep/gone.md")
        keep_directory = [str(r.uri) for r in await client.extension(ClientSkills).read_directory("skill://keep")]

    assert changes == catalog_module.SkillCatalogChanges(
        added=("skill://new/SKILL.md",),
        removed=("skill://old/SKILL.md",),
        changed=("skill://keep/SKILL.md",),
    )
    assert listed == ["skill://keep/SKILL.md", "skill://new/SKILL.md"]
    assert resources == ["skill://keep/SKILL.md", "skill://keep/added.md", "skill://new/SKILL.md"]
    assert isinstance(added, TextResourceContents)
    assert added.text == "added"
    assert gone.value.code == INVALID_PARAMS
    assert keep_directory == ["skill://keep/SKILL.md", "skill://keep/added.md"]


async def test_reload_serves_a_renamed_file_at_its_new_uri_after_lookups_have_used_the_old_one() -> None:
    """SDK-defined: each reload publishes a new tuple of new resources, so the server's URI index never goes stale."""
    provider, catalog, server = await _reloadable({"guide/SKILL.md": _skill_md("guide"), "guide/old-name.md": b"notes"})
    async with Client(server) as client:
        before = (await client.read_resource("skill://guide/old-name.md")).contents[0]
        published = catalog.resources()
        provider.files = {"guide/SKILL.md": _skill_md("guide"), "guide/new-name.md": b"notes"}
        await catalog.reload()
        after = (await client.read_resource("skill://guide/new-name.md")).contents[0]
        with pytest.raises(MCPError) as old_uri:
            await client.read_resource("skill://guide/old-name.md")

    assert isinstance(before, TextResourceContents)
    assert before.text == "notes"
    assert isinstance(after, TextResourceContents)
    assert after.text == "notes"
    assert old_uri.value.code == INVALID_PARAMS
    assert catalog.resources() is not published
    assert [str(binding.resource.uri) for binding in published] == [
        "skill://guide/SKILL.md",
        "skill://guide/old-name.md",
    ]


async def test_reload_reports_a_nested_skill_that_is_removed_and_comes_back() -> None:
    """SDK-defined: a nested skill's files are also served through its parent, so it can come and go on reload."""
    provider, catalog, server = await _reloadable(
        {
            "acme/SKILL.md": _skill_md("acme"),
            "acme/billing/SKILL.md": _skill_md("billing"),
        }
    )
    del provider.files["acme/billing/SKILL.md"]
    async with Client(server, extensions=[ClientSkills()]) as client:
        removed = await catalog.reload()
        listed_while_removed = [skill.uri for skill in await client.extension(ClientSkills).list_skills()]
        provider.files["acme/billing/SKILL.md"] = _skill_md("billing")
        restored = await catalog.reload()
        listed_after_restore = [skill.uri for skill in await client.extension(ClientSkills).list_skills()]

    assert removed.removed == ("skill://acme/billing/SKILL.md",)
    assert listed_while_removed == ["skill://acme/SKILL.md"]
    assert restored.added == ("skill://acme/billing/SKILL.md",)
    assert listed_after_restore == ["skill://acme/SKILL.md", "skill://acme/billing/SKILL.md"]


async def test_reload_keeps_the_old_catalog_when_an_edit_makes_a_served_skill_invalid() -> None:
    """SDK-defined: a typo mid-edit doesn't take the skill down, even when `strict` is off."""
    provider, catalog, server = await _reloadable({"git-workflow/SKILL.md": _skill_md("git-workflow")})
    old_skill_md = provider.files["git-workflow/SKILL.md"]
    provider.files["git-workflow/SKILL.md"] = b"not frontmatter"
    provider.files["new/SKILL.md"] = _skill_md("new")
    async with Client(server, extensions=[ClientSkills()]) as client:
        with pytest.raises(ValueError, match="invalid skills"):
            await catalog.reload()
        skills = await client.extension(ClientSkills).list_skills()
        provider.files["git-workflow/SKILL.md"] = old_skill_md
        await catalog.reload()
        skills_after_fix = await client.extension(ClientSkills).list_skills()

    assert [skill.uri for skill in skills] == ["skill://git-workflow/SKILL.md"]
    assert [skill.uri for skill in skills_after_fix] == ["skill://git-workflow/SKILL.md", "skill://new/SKILL.md"]


async def test_reload_tolerates_skills_skipped_at_load_and_warns_about_new_ones_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SDK-defined: without `strict`, a skill skipped at load doesn't block reloads or repeat warnings."""
    provider, catalog, _ = await _reloadable(
        {"git-workflow/SKILL.md": _skill_md("git-workflow"), "broken/SKILL.md": b"not frontmatter"}
    )
    provider.files["another/SKILL.md"] = b"not frontmatter"
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=CATALOG_LOGGER):
        await catalog.reload()
        await catalog.reload()

    assert [record.message for record in caplog.records if record.name == CATALOG_LOGGER] == [
        "Skipping invalid skill: another/SKILL.md: SKILL.md must start with a '---' frontmatter line"
    ]


async def test_a_strict_reload_raises_for_an_invalid_skill() -> None:
    """SDK-defined: `strict` applies to every scan, so a reload reports invalid skills the way `load()` does."""
    provider, catalog, _ = await _reloadable({"git-workflow/SKILL.md": _skill_md("git-workflow")}, strict=True)
    provider.files["git-workflow/SKILL.md"] = b"not frontmatter"

    with pytest.raises(ValueError, match="invalid skills"):
        await catalog.reload()


async def test_a_provider_failure_during_reload_propagates_and_the_old_catalog_keeps_serving() -> None:
    """SDK-defined: only a clean rescan is applied."""
    provider, catalog, server = await _reloadable({"git-workflow/SKILL.md": _skill_md("git-workflow")})
    del provider.files["git-workflow/SKILL.md"]
    provider._listing = ["git-workflow/SKILL.md"]
    async with Client(server, extensions=[ClientSkills()]) as client:
        with pytest.raises(KeyError):
            await catalog.reload()
        skills = await client.extension(ClientSkills).list_skills()

    assert [skill.uri for skill in skills] == ["skill://git-workflow/SKILL.md"]


async def test_a_catalog_built_directly_has_no_provider_to_reload() -> None:
    """SDK-defined: `reload()` needs the provider that `SkillCatalog.load()` records."""
    catalog = SkillCatalog(skills=[], files={}, directories=None, ttl_ms=0, cache_scope="private", page_size=None)

    with pytest.raises(RuntimeError):
        await catalog.reload()


async def test_cancelling_a_reload_preserves_the_snapshot_and_releases_the_scan_lock() -> None:
    """SDK-defined: cancellation before publication leaves the old bytes readable and permits a later reload."""
    scanning = anyio.Event()
    release = anyio.Event()

    class GatedProvider(_MemoryProvider):
        block = False

        async def read_file(self, path: str) -> bytes:
            if self.block:
                scanning.set()
                await release.wait()
            return await super().read_file(path)

    old_md = _skill_md("git-workflow")
    provider = GatedProvider({"git-workflow/SKILL.md": old_md})
    catalog = await SkillCatalog.load(provider, parse_frontmatter=_parse, auto_refresh=True)
    server = MCPServer("skills", extensions=[catalog])
    with anyio.fail_after(5):
        async with Client(server, extensions=[ClientSkills()]) as client:
            before = await client.extension(ClientSkills).list_skills()
            provider.files["git-workflow/SKILL.md"] = _skill_md("git-workflow", "Updated")
            provider.block = True
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(catalog.reload)
                await scanning.wait()
                tasks.cancel_scope.cancel()

            assert await client.extension(ClientSkills).list_skills() == before
            contents = (await client.read_resource(before[0].uri)).contents[0]
            assert isinstance(contents, TextResourceContents)
            assert contents.text.encode("utf-8") == old_md

            provider.block = False
            changes = await catalog.reload()
            assert changes.changed == (before[0].uri,)
            assert (await client.extension(ClientSkills).get_skill(before[0].uri)).frontmatter[
                "description"
            ] == "Updated"


async def test_concurrent_reloads_scan_one_at_a_time_and_compare_with_the_last_published_generation() -> None:
    """SDK-defined: overlapping reload calls serialize, so only the first reports an added skill."""
    scanning, release, second_started = anyio.Event(), anyio.Event(), anyio.Event()
    scans: list[str] = []

    class GatedProvider(_MemoryProvider):
        block = False

        async def list_files(self) -> Sequence[str]:
            if self.block:
                scans.append("scan")
                if len(scans) == 1:
                    scanning.set()
                    await release.wait()
            return await super().list_files()

    provider = GatedProvider({})
    catalog = await SkillCatalog.load(provider, parse_frontmatter=_parse)
    provider.files["new/SKILL.md"] = _skill_md("new")
    provider.block = True
    changes: list[catalog_module.SkillCatalogChanges] = []

    async def first() -> None:
        changes.append(await catalog.reload())

    async def second() -> None:
        second_started.set()
        changes.append(await catalog.reload())

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(first)
            await scanning.wait()
            tasks.start_soon(second)
            await second_started.wait()
            await anyio.wait_all_tasks_blocked()
            assert scans == ["scan"]
            release.set()

    assert scans == ["scan", "scan"]
    assert changes == [
        catalog_module.SkillCatalogChanges(added=("skill://new/SKILL.md",), removed=(), changed=()),
        catalog_module.SkillCatalogChanges(added=(), removed=(), changed=()),
    ]
    assert [skill.uri for skill in await _listed(catalog)] == ["skill://new/SKILL.md"]


async def test_the_handler_aliases_stay_importable_from_the_package() -> None:
    """Compatibility: `mcp.server.skills` was a module before it became a package; its public names survive."""
    assert (GetSkillHandler, ListSkillsHandler, ReadDirectoryHandler) == (
        skills_package.GetSkillHandler,
        skills_package.ListSkillsHandler,
        skills_package.ReadDirectoryHandler,
    )
    assert skills_package.__all__ == [
        "Skills",
        "SkillCatalog",
        "SkillProvider",
        "FilesystemSkillProvider",
    ]
    assert not hasattr(skills_package, "SkillCatalogChanges")


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
