"""SEP-2640 conformance checks in `mcp.shared.skills`: types, validation, and verification.

Server- and client-side end-to-end wiring live in `tests/server/test_skills.py` and
`tests/client/test_skills.py`; this file pins the pure functions both depend on.
"""

import hashlib

import pytest
from mcp_types import Resource

from mcp.shared.skills import (
    ListSkillsResult,
    ReadDirectoryResult,
    Skill,
    SkillResource,
    parse_directory_uri,
    skill_name_from_uri,
    validate_directory_result,
    validate_list_result,
    validate_skill,
    verify_skill_resource,
)

_DIGEST = "sha256:" + "a" * 64


def _resource(uri: str, *, size: int = 4) -> SkillResource:
    return SkillResource(uri=uri, digest=_DIGEST, size=size)


def _skill(name: str = "git-workflow", *, extra_resources: list[SkillResource] | None = None) -> Skill:
    uri = f"skill://{name}/SKILL.md"
    return Skill(
        uri=uri,
        frontmatter={"name": name, "description": "d"},
        resources=[_resource(uri), *(extra_resources or [])],
    )


@pytest.mark.parametrize(
    ("uri", "name"),
    [
        ("skill://git-workflow/SKILL.md", "git-workflow"),
        ("skill://acme/billing/refunds/SKILL.md", "refunds"),
        ("https://example.com/skills/pdf/SKILL.md", "pdf"),
    ],
)
def test_skill_name_from_uri_reads_the_final_path_segment(uri: str, name: str) -> None:
    """SEP-2640 Resource Mapping: the final `<skill-path>` segment is the skill name."""
    assert skill_name_from_uri(uri) == name


@pytest.mark.parametrize(
    "uri",
    [
        "skill://git-workflow/README.md",  # doesn't end in /SKILL.md
        "not-a-uri",  # no scheme
        "skill://git-workflow/SKILL.md?x=1",  # query component
    ],
)
def test_skill_name_from_uri_rejects_malformed_uris(uri: str) -> None:
    with pytest.raises(ValueError, match="SKILL.md|absolute resource URI"):
        skill_name_from_uri(uri)


def test_skill_name_from_uri_rejects_a_uri_with_no_recoverable_name() -> None:
    with pytest.raises(ValueError, match="has no skill name"):
        skill_name_from_uri("skill:///SKILL.md")


def test_skill_with_a_static_resources_array_round_trips_through_json() -> None:
    """SEP-2640 Resources: `resources` MUST serialize as a JSON array of `{uri, digest, size}`
    triples - proves the union type doesn't collapse or mistag on the wire."""
    original = _skill()
    dumped = original.model_dump(mode="json", by_alias=True)
    assert isinstance(dumped["resources"], list)
    restored = Skill.model_validate(dumped)
    assert restored == original


def test_skill_with_dynamic_resources_round_trips_through_json_as_the_literal_string() -> None:
    """SEP-2640 Resources: a dynamically generated skill MUST carry the literal string
    `"dynamic"` in place of an array - not `null`, not `{}`, not omitted."""
    original = Skill(
        uri="skill://generated/SKILL.md", frontmatter={"name": "generated", "description": "d"}, resources="dynamic"
    )
    dumped = original.model_dump(mode="json", by_alias=True)
    assert dumped["resources"] == "dynamic"
    restored = Skill.model_validate(dumped)
    assert restored == original
    assert restored.resources == "dynamic"


def test_validate_skill_accepts_a_conformant_skill() -> None:
    validate_skill(_skill())


def test_validate_skill_rejects_a_non_string_frontmatter_name() -> None:
    skill = Skill(
        uri="skill://git-workflow/SKILL.md",
        frontmatter={"name": 1, "description": "d"},
        resources=[_resource("skill://git-workflow/SKILL.md")],
    )
    with pytest.raises(ValueError, match="frontmatter name"):
        validate_skill(skill)


@pytest.mark.parametrize(
    "name",
    [
        "foo--bar",  # consecutive hyphens
        "-foo",  # leading hyphen
        "foo-",  # trailing hyphen
        "UPPER",  # uppercase not allowed
        "with_underscore",  # underscore not allowed
        "a" * 65,  # exceeds the 64-char limit
    ],
)
def test_validate_skill_rejects_names_violating_the_agent_skills_grammar(name: str) -> None:
    """SEP-2640 defers naming to the Agent Skills spec: 1-64 chars, lowercase alphanumeric and
    hyphens, no leading/trailing/consecutive hyphens. A URI whose final path segment carries the
    bad name (so `frontmatter.name` can match it) still fails the name-grammar check first."""
    uri = f"skill://acme/{name}/SKILL.md"
    skill = Skill(
        uri=uri,
        frontmatter={"name": name, "description": "d"},
        resources=[SkillResource(uri=uri, digest=_DIGEST, size=4)],
    )
    with pytest.raises(ValueError, match="frontmatter name"):
        validate_skill(skill)


def test_validate_skill_rejects_an_invalid_resource_uri() -> None:
    """A resource URI with a query component fails the same shape check as a skill URI."""
    skill = _skill(extra_resources=[_resource("skill://git-workflow/x.md?y=1")])
    with pytest.raises(ValueError, match="is invalid"):
        validate_skill(skill)


def test_validate_skill_rejects_a_resource_with_the_same_authority_but_a_sibling_path() -> None:
    """Same scheme+authority as the skill (so the URI passes the authority check) but a path
    outside the skill's own directory, per SEP-2640 Resources ('a file within the skill's
    directory')."""
    root = "skill://acme/billing/refunds/SKILL.md"
    skill = Skill(
        uri=root,
        frontmatter={"name": "refunds", "description": "d"},
        resources=[_resource(root), _resource("skill://acme/billing/other/x.md")],
    )
    with pytest.raises(ValueError, match="outside the skill root"):
        validate_skill(skill)


def test_validate_skill_rejects_a_traversal_segment_in_a_resource_uri() -> None:
    skill = _skill(extra_resources=[_resource("skill://git-workflow/../evil.md")])
    with pytest.raises(ValueError, match="traversal segment"):
        validate_skill(skill)


def test_validate_skill_rejects_a_negative_resource_size() -> None:
    root = "skill://git-workflow/SKILL.md"
    skill = Skill(
        uri=root,
        frontmatter={"name": "git-workflow", "description": "d"},
        resources=[SkillResource(uri=root, digest=_DIGEST, size=-1)],
    )
    with pytest.raises(ValueError, match="negative size"):
        validate_skill(skill)


def test_validate_skill_rejects_frontmatter_name_uri_mismatch() -> None:
    """SEP-2640 Resource Mapping: `frontmatter.name` MUST equal the URI-derived name."""
    skill = Skill(
        uri="skill://git-workflow/SKILL.md",
        frontmatter={"name": "other-name", "description": "d"},
        resources=[_resource("skill://git-workflow/SKILL.md")],
    )
    with pytest.raises(ValueError, match="does not match URI name"):
        validate_skill(skill)


@pytest.mark.parametrize("description", ["", "x" * 1025])
def test_validate_skill_rejects_out_of_range_description_length(description: str) -> None:
    skill = Skill(
        uri="skill://git-workflow/SKILL.md",
        frontmatter={"name": "git-workflow", "description": description},
        resources=[_resource("skill://git-workflow/SKILL.md")],
    )
    with pytest.raises(ValueError, match="description"):
        validate_skill(skill)


def test_validate_skill_rejects_a_resource_outside_the_skill_root() -> None:
    """SEP-2640 Resources: every entry MUST name a file within the skill's own directory."""
    skill = _skill(extra_resources=[_resource("skill://other-skill/file.md")])
    with pytest.raises(ValueError, match="outside the skill root"):
        validate_skill(skill)


def test_validate_skill_rejects_missing_skill_md_entry() -> None:
    """SEP-2640 Resources: `resources` MUST include an entry for the skill's own `SKILL.md`."""
    skill = Skill(
        uri="skill://git-workflow/SKILL.md",
        frontmatter={"name": "git-workflow", "description": "d"},
        resources=[_resource("skill://git-workflow/references/GUIDE.md")],
    )
    with pytest.raises(ValueError, match="does not include its own SKILL.md"):
        validate_skill(skill)


def test_validate_skill_rejects_duplicate_resource_uris() -> None:
    root = "skill://git-workflow/SKILL.md"
    skill = Skill(
        uri=root, frontmatter={"name": "git-workflow", "description": "d"}, resources=[_resource(root), _resource(root)]
    )
    with pytest.raises(ValueError, match="more than once"):
        validate_skill(skill)


@pytest.mark.parametrize(
    "digest",
    [
        "not-a-digest",  # no sha256: prefix at all
        "sha256:" + "A" * 64,  # uppercase hex - spec requires lowercase
        "sha256:" + "a" * 63,  # one hex char short
        "sha256:" + "a" * 65,  # one hex char long
        "sha1:" + "a" * 40,  # wrong algorithm prefix
        "sha256:" + "g" * 64,  # non-hex characters
    ],
)
def test_validate_skill_rejects_malformed_digest_formats(digest: str) -> None:
    """SEP-2640 Integrity and verification: `sha256:{hex}` where `{hex}` is exactly 64
    lowercase hexadecimal characters - each of these near-misses must still be rejected."""
    root = "skill://git-workflow/SKILL.md"
    bad = SkillResource(uri=root, digest=digest, size=1)
    skill = Skill(uri=root, frontmatter={"name": "git-workflow", "description": "d"}, resources=[bad])
    with pytest.raises(ValueError, match="digest"):
        validate_skill(skill)


def test_validate_skill_rejects_more_than_512_resources() -> None:
    """SEP-2640 Limits: 512 entries per skill, `SKILL.md` included."""
    root = "skill://git-workflow/SKILL.md"
    resources = [_resource(root)] + [_resource(f"skill://git-workflow/f{i}.md") for i in range(512)]
    skill = Skill(uri=root, frontmatter={"name": "git-workflow", "description": "d"}, resources=resources)
    with pytest.raises(ValueError, match="exceeding 512"):
        validate_skill(skill)


def test_validate_skill_rejects_total_size_over_16mib() -> None:
    """SEP-2640 Limits: 16 MiB total per skill, summed over `resources[].size`."""
    root = "skill://git-workflow/SKILL.md"
    skill = Skill(
        uri=root,
        frontmatter={"name": "git-workflow", "description": "d"},
        resources=[_resource(root, size=16 * 1024 * 1024 + 1)],
    )
    with pytest.raises(ValueError, match="exceeding"):
        validate_skill(skill)


def test_validate_skill_accepts_dynamic_resources_without_further_checks() -> None:
    """SEP-2640 Resources: `"dynamic"` offers no manifest to check against limits."""
    skill = Skill(
        uri="skill://generated/SKILL.md", frontmatter={"name": "generated", "description": "d"}, resources="dynamic"
    )
    validate_skill(skill)


def test_validate_list_result_rejects_duplicate_skill_uris_across_entries() -> None:
    result = ListSkillsResult(skills=[_skill(), _skill()])
    with pytest.raises(ValueError, match="more than once"):
        validate_list_result(result)


def test_validate_list_result_accepts_an_empty_listing() -> None:
    """SEP-2640 Enumeration: `skills/list` MAY return an empty result."""
    validate_list_result(ListSkillsResult(skills=[]))


@pytest.mark.parametrize("uri", ["skill://pdf/templates/", "not-a-uri"])
def test_parse_directory_uri_rejects_malformed_uris(uri: str) -> None:
    with pytest.raises(ValueError, match="directory URI"):
        parse_directory_uri(uri)


def test_validate_directory_result_rejects_a_child_with_a_query_component() -> None:
    result = ReadDirectoryResult(resources=[Resource(uri="skill://pdf/templates/x.md?y=1", name="x.md")])
    with pytest.raises(ValueError, match="invalid URI"):
        validate_directory_result("skill://pdf/templates", result)


def test_validate_directory_result_rejects_a_duplicate_child_name() -> None:
    result = ReadDirectoryResult(
        resources=[
            Resource(uri="skill://pdf/templates/a.md", name="dup"),
            Resource(uri="skill://pdf/templates/b.md", name="dup"),
        ]
    )
    with pytest.raises(ValueError, match="duplicate child"):
        validate_directory_result("skill://pdf/templates", result)


def test_validate_directory_result_accepts_direct_children() -> None:
    result = ReadDirectoryResult(
        resources=[
            Resource(uri="skill://pdf/templates/invoice.md", name="invoice.md", mime_type="text/markdown"),
            Resource(uri="skill://pdf/templates/regional", name="regional", mime_type="inode/directory"),
        ]
    )
    validate_directory_result("skill://pdf/templates", result)


def test_validate_directory_result_rejects_a_grandchild() -> None:
    """SEP-2640 Directory Listing: the listing is not recursive."""
    result = ReadDirectoryResult(
        resources=[Resource(uri="skill://pdf/templates/regional/eu.md", name="eu.md", mime_type="text/markdown")]
    )
    with pytest.raises(ValueError, match="direct child"):
        validate_directory_result("skill://pdf/templates", result)


def test_validate_directory_result_rejects_a_uri_outside_the_directory() -> None:
    result = ReadDirectoryResult(resources=[Resource(uri="skill://other/file.md", name="file.md")])
    with pytest.raises(ValueError, match="not a child"):
        validate_directory_result("skill://pdf/templates", result)


def test_verify_skill_resource_accepts_matching_content() -> None:
    content = b"hello skill"
    digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    uri = "skill://git-workflow/SKILL.md"
    skill = Skill(
        uri=uri,
        frontmatter={"name": "git-workflow", "description": "d"},
        resources=[SkillResource(uri=uri, digest=digest, size=len(content))],
    )
    verify_skill_resource(skill, uri, content)


def test_verify_skill_resource_rejects_a_digest_mismatch() -> None:
    """SEP-2640 Integrity and verification: a mismatch MUST be treated as a verification failure."""
    uri = "skill://git-workflow/SKILL.md"
    skill = Skill(
        uri=uri,
        frontmatter={"name": "git-workflow", "description": "d"},
        resources=[SkillResource(uri=uri, digest=_DIGEST, size=5)],
    )
    with pytest.raises(ValueError, match="digest"):
        verify_skill_resource(skill, uri, b"wrong")


def test_verify_skill_resource_rejects_a_size_mismatch_before_hashing() -> None:
    uri = "skill://git-workflow/SKILL.md"
    skill = Skill(
        uri=uri,
        frontmatter={"name": "git-workflow", "description": "d"},
        resources=[SkillResource(uri=uri, digest=_DIGEST, size=999)],
    )
    with pytest.raises(ValueError, match="size"):
        verify_skill_resource(skill, uri, b"short")


def test_verify_skill_resource_rejects_dynamic_resources() -> None:
    uri = "skill://generated/SKILL.md"
    skill = Skill(uri=uri, frontmatter={"name": "generated", "description": "d"}, resources="dynamic")
    with pytest.raises(ValueError, match="dynamic"):
        verify_skill_resource(skill, uri, b"anything")


def test_verify_skill_resource_rejects_a_uri_not_in_the_manifest() -> None:
    skill = _skill()
    with pytest.raises(ValueError, match="not in skill"):
        verify_skill_resource(skill, "skill://git-workflow/unlisted.md", b"x")
