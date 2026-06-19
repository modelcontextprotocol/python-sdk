"""Enforces the contract between the requirements manifest and the test suite.

The contract runs in both directions: every non-deferred entry in :data:`REQUIREMENTS` must be
exercised by at least one test, and every test in the suite must carry at least one
`@requirement(...)` mark referencing a manifest entry. Deferral reasons that point at coverage
elsewhere in the repo must point at paths that exist. Test modules are imported directly
(rather than relying on pytest collection) so the check holds even when only this file is run.
"""

import importlib
import re
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

from mcp.shared.version import KNOWN_PROTOCOL_VERSIONS
from mcp.types import LATEST_PROTOCOL_VERSION
from tests.interaction._requirements import (
    CONNECTABLE_TRANSPORTS,
    REQUIREMENTS,
    SPEC_2026_BASE_URL,
    SPEC_BASE_URL,
    SPEC_VERSIONS,
    ArmExclusion,
    KnownFailure,
    Requirement,
    SpecVersion,
    Transport,
    cell_id,
    compute_cells,
    covered_by,
    requirement,
)
from tests.interaction.conftest import _FACTORIES

_SUITE_ROOT = Path(__file__).parent
_REPO_ROOT = _SUITE_ROOT.parent.parent

# Repo paths cited inside deferral reasons ("Covered by tests/... ").
_CITED_PATH = re.compile(r"(?:tests|src)/[\w./-]*\w")

# Tests that exercise the suite's own helpers rather than an interaction-model behaviour.
# Anything listed here is exempt from the every-test-has-a-requirement check.
_HARNESS_SELF_TESTS = {
    "tests.interaction.lowlevel.test_wire.test_recording_read_stream_ends_iteration_when_the_sender_closes",
    "tests.interaction.transports.test_bridge.test_response_chunks_arrive_as_the_application_sends_them",
    "tests.interaction.transports.test_bridge.test_closing_the_response_delivers_a_disconnect_to_the_application",
    "tests.interaction.transports.test_bridge.test_an_application_failure_before_the_response_starts_fails_the_request",
    "tests.interaction.transports.test_bridge.test_disabling_cancel_on_close_lets_the_application_finish_after_disconnect",
    "tests.interaction.auth.test_flow.test_shimmed_app_serves_overrides_404s_and_otherwise_forwards_to_the_wrapped_app",
}


def _import_all_test_modules() -> list[ModuleType]:
    """Import every other test module in the suite so their `@requirement` decorators register."""
    modules: list[ModuleType] = []
    for path in sorted(_SUITE_ROOT.rglob("test_*.py")):
        relative = path.relative_to(_SUITE_ROOT).with_suffix("")
        name = f"{__package__}.{'.'.join(relative.parts)}"
        if name != __name__:
            modules.append(importlib.import_module(name))
    return modules


def test_every_requirement_is_exercised() -> None:
    """Each non-deferred requirement is covered by at least one test (deferred ones by none)."""
    _import_all_test_modules()

    uncovered = [
        requirement_id
        for requirement_id, spec in sorted(REQUIREMENTS.items())
        if spec.deferred is None and not covered_by(requirement_id)
    ]
    assert not uncovered, f"Requirements with no test and no deferred reason: {uncovered}"

    stale_deferrals = [
        requirement_id
        for requirement_id, spec in sorted(REQUIREMENTS.items())
        if spec.deferred is not None and covered_by(requirement_id)
    ]
    assert not stale_deferrals, f"Deferred requirements that now have tests (remove deferred): {stale_deferrals}"


def test_every_test_exercises_a_requirement() -> None:
    """Each test in the suite carries at least one `@requirement` mark (harness self-tests excepted)."""
    all_tests = {
        f"{module.__name__}.{name}"
        for module in _import_all_test_modules()
        for name in vars(module)
        if name.startswith("test_")
    }
    linked_tests = {test_name for requirement_id in REQUIREMENTS for test_name in covered_by(requirement_id)}

    unlinked = sorted(all_tests - linked_tests - _HARNESS_SELF_TESTS)
    assert not unlinked, f"Tests with no @requirement mark: {unlinked}"

    stale_exemptions = sorted(_HARNESS_SELF_TESTS - all_tests)
    assert not stale_exemptions, f"Harness self-test exemptions that no longer exist: {stale_exemptions}"


def test_deferral_reasons_cite_existing_paths() -> None:
    """Every repo path named in a deferral reason exists, so coverage pointers cannot rot."""
    missing = sorted(
        f"{requirement_id}: {cited}"
        for requirement_id, spec in REQUIREMENTS.items()
        if spec.deferred is not None
        for cited in _CITED_PATH.findall(spec.deferred)
        if not (_REPO_ROOT / cited).exists()
    )
    assert not missing, f"Deferral reasons citing paths that do not exist: {missing}"


def test_spec_versions_are_known_and_include_latest() -> None:
    """Every active spec version is one the SDK knows about, and the SDK's latest is on the active axis."""
    assert set(SPEC_VERSIONS) <= set(KNOWN_PROTOCOL_VERSIONS)
    assert LATEST_PROTOCOL_VERSION in SPEC_VERSIONS


def test_spec_base_urls_are_pinned_to_their_revision() -> None:
    """SPEC_BASE_URL constants are pinned literals, so growing SPEC_VERSIONS cannot repoint existing source links."""
    assert SPEC_BASE_URL == "https://modelcontextprotocol.io/specification/2025-11-25"
    assert SPEC_2026_BASE_URL == "https://modelcontextprotocol.io/specification/2026-07-28"


def test_connectable_transports_match_connect_factories() -> None:
    """CONNECTABLE_TRANSPORTS and the conftest factory map name exactly the same transports."""
    assert set(CONNECTABLE_TRANSPORTS) == set(_FACTORIES)


def test_supersession_links_are_symmetric_and_versioned() -> None:
    """``supersedes``/``superseded_by`` reference real entries, agree in both directions, and carry version bounds."""
    broken = [
        f"{req_id} -> {target}"
        for req_id, req in REQUIREMENTS.items()
        for target in req.supersedes
        if target not in REQUIREMENTS or REQUIREMENTS[target].superseded_by != req_id or req.added_in is None
    ] + [
        f"{req_id} <- {req.superseded_by}"
        for req_id, req in REQUIREMENTS.items()
        if req.superseded_by is not None
        if req.superseded_by not in REQUIREMENTS
        or req_id not in REQUIREMENTS[req.superseded_by].supersedes
        or req.removed_in is None
    ]
    assert not broken, f"Broken supersession links (forward '->' or back '<-'): {broken}"


def test_removed_entry_has_disposition() -> None:
    """Every retired requirement carries either a forward link or a prose note explaining the retirement."""
    undisposed = [
        req_id
        for req_id, req in REQUIREMENTS.items()
        if req.removed_in is not None and req.superseded_by is None and req.note is None
    ]
    assert not undisposed, f"Requirements with removed_in but no superseded_by or note: {undisposed}"


def test_transport_restriction_has_note() -> None:
    """Every transport-restricted requirement carries a note explaining why it is transport-specific."""
    missing = [req_id for req_id, req in REQUIREMENTS.items() if req.transports is not None and req.note is None]
    assert not missing, f"Requirements with transports= but no note: {missing}"


def test_every_arm_exclusion_targets_a_reachable_cell() -> None:
    """Every arm exclusion names a connectable transport (or wildcards).

    spec_version is type-checked against the SpecVersion Literal and may reference a version not yet
    on the active SPEC_VERSIONS axis, so pre-staged exclusions for an upcoming revision are permitted.
    """
    unreachable = [
        f"{req_id}: {exclusion}"
        for req_id, req in REQUIREMENTS.items()
        for exclusion in req.arm_exclusions
        if exclusion.transport is not None and exclusion.transport not in CONNECTABLE_TRANSPORTS
    ]
    assert not unreachable, f"Arm exclusions targeting unreachable cells: {unreachable}"


def test_every_known_failure_targets_a_reachable_cell() -> None:
    """Every known failure names a connectable transport (or wildcards).

    spec_version is type-checked against the SpecVersion Literal and may reference a version not yet
    on the active SPEC_VERSIONS axis, so pre-staged exclusions for an upcoming revision are permitted.
    """
    unreachable = [
        f"{req_id}: {failure}"
        for req_id, req in REQUIREMENTS.items()
        for failure in req.known_failures
        if failure.transport is not None and failure.transport not in CONNECTABLE_TRANSPORTS
    ]
    assert not unreachable, f"Known failures targeting unreachable cells: {unreachable}"


def test_unknown_requirement_id_is_rejected() -> None:
    """Marking a test with an ID that is not in the manifest fails at decoration time."""
    with pytest.raises(KeyError, match="Unknown requirement id 'tools:call:does-not-exist'"):
        requirement("tools:call:does-not-exist")


def test_invalid_requirement_source_is_rejected() -> None:
    """A requirement whose source is not a spec URL, 'sdk', or an issue reference fails at construction."""
    with pytest.raises(ValueError, match="source must be a specification URL"):
        Requirement(source="https://example.com/not-the-spec", behavior="Never constructed.")


def test_arm_exclusion_with_unknown_spec_version_is_rejected() -> None:
    """An arm exclusion naming a spec version outside KNOWN_PROTOCOL_VERSIONS fails at construction."""
    with pytest.raises(ValueError, match="is not in KNOWN_PROTOCOL_VERSIONS"):
        ArmExclusion(reason="requires-session", spec_version=cast("SpecVersion", "2099-01-01"))


def test_known_failure_with_empty_note_is_rejected() -> None:
    """A known failure with a blank note fails at construction."""
    with pytest.raises(ValueError, match="note must be non-empty"):
        KnownFailure(note="   ")


def test_known_failure_with_unknown_spec_version_is_rejected() -> None:
    """A known failure naming a spec version outside KNOWN_PROTOCOL_VERSIONS fails at construction."""
    with pytest.raises(ValueError, match="is not in KNOWN_PROTOCOL_VERSIONS"):
        KnownFailure(note="x", spec_version=cast("SpecVersion", "2099-01-01"))


def test_known_failure_with_malformed_issue_is_rejected() -> None:
    """A known failure whose issue reference is neither '#<n>' nor a GitHub URL fails at construction."""
    with pytest.raises(ValueError, match="must be '#<n>' or a GitHub URL"):
        KnownFailure(note="x", issue="not-a-link")


def test_requirement_with_unknown_added_in_is_rejected() -> None:
    """A requirement whose added_in is outside KNOWN_PROTOCOL_VERSIONS fails at construction."""
    with pytest.raises(ValueError, match="added_in .* is not in KNOWN_PROTOCOL_VERSIONS"):
        Requirement(source="sdk", behavior="x", added_in=cast("SpecVersion", "2099-01-01"))


def test_requirement_with_unknown_removed_in_is_rejected() -> None:
    """A requirement whose removed_in is outside KNOWN_PROTOCOL_VERSIONS fails at construction."""
    with pytest.raises(ValueError, match="removed_in .* is not in KNOWN_PROTOCOL_VERSIONS"):
        Requirement(source="sdk", behavior="x", removed_in=cast("SpecVersion", "2099-01-01"))


def test_requirement_with_empty_version_range_is_rejected() -> None:
    """A requirement whose added_in is not strictly earlier than its removed_in fails at construction."""
    with pytest.raises(ValueError, match="must be earlier than"):
        Requirement(source="sdk", behavior="x", added_in="2025-11-25", removed_in="2025-11-25")


def _req(
    *,
    added_in: SpecVersion | None = None,
    removed_in: SpecVersion | None = None,
    transports: tuple[Transport, ...] | None = None,
    arm_exclusions: tuple[ArmExclusion, ...] = (),
    known_failures: tuple[KnownFailure, ...] = (),
) -> Requirement:
    """Build a synthetic Requirement for compute_cells() unit tests."""
    return Requirement(
        source="sdk",
        behavior="x",
        added_in=added_in,
        removed_in=removed_in,
        transports=transports,
        arm_exclusions=arm_exclusions,
        known_failures=known_failures,
    )


def test_compute_cells_with_no_requirements_yields_full_grid() -> None:
    """With a single-version axis, an empty requirement list yields one cell per connectable transport."""
    cells = compute_cells([], spec_versions=("2025-11-25",))
    assert [c.id for c in cells] == ["in-memory", "sse", "streamable-http", "streamable-http-stateless"]
    assert [c.values for c in cells] == [
        (("in-memory", "2025-11-25"),),
        (("sse", "2025-11-25"),),
        (("streamable-http", "2025-11-25"),),
        (("streamable-http-stateless", "2025-11-25"),),
    ]


def test_compute_cells_intersects_stacked_version_ranges() -> None:
    """Stacked requirements intersect their [added_in, removed_in) windows: a cell survives only if all admit it."""
    cells = compute_cells(
        [_req(removed_in="2026-07-28"), _req(added_in="2025-11-25")],
        spec_versions=("2025-11-25", "2026-07-28"),
    )
    assert [c.id for c in cells] == [
        "in-memory-2025-11-25",
        "sse-2025-11-25",
        "streamable-http-2025-11-25",
        "streamable-http-stateless-2025-11-25",
    ]


def test_compute_cells_drops_era_locked_transport_outside_its_versions() -> None:
    """A transport listed in TRANSPORT_SPEC_VERSIONS only appears for the spec versions it serves."""
    cells = compute_cells([], spec_versions=("2025-11-25", "2026-07-28"))
    assert [c.id for c in cells] == [
        "in-memory-2025-11-25",
        "sse-2025-11-25",
        "streamable-http-2025-11-25",
        "streamable-http-stateless-2025-11-25",
        "in-memory-2026-07-28",
        "streamable-http-2026-07-28",
        "streamable-http-stateless-2026-07-28",
    ]


def test_compute_cells_honours_arm_exclusion_from_any_stacked_requirement() -> None:
    """An arm exclusion on any stacked requirement drops the matching cell even when other requirements have none."""
    cells = compute_cells(
        [_req(), _req(arm_exclusions=(ArmExclusion(reason="requires-session", transport="sse"),))],
        spec_versions=("2025-11-25",),
    )
    assert [c.id for c in cells] == ["in-memory", "streamable-http", "streamable-http-stateless"]


def test_compute_cells_wildcard_arm_exclusion_drops_every_cell() -> None:
    """An arm exclusion with both transport and spec_version unset matches every cell, leaving none."""
    cells = compute_cells([_req(arm_exclusions=(ArmExclusion(reason="requires-session"),))])
    assert cells == []


def test_compute_cells_marks_known_failure_as_strict_xfail() -> None:
    """A known failure attaches a strict xfail mark to exactly the matching cell and leaves others unmarked."""
    cells = compute_cells(
        [_req(known_failures=(KnownFailure(note="broken on sse", transport="sse"),))],
        spec_versions=("2025-11-25",),
    )
    by_id = {c.id: c for c in cells}
    assert set(by_id) == {"in-memory", "sse", "streamable-http", "streamable-http-stateless"}
    assert by_id["sse"].marks[0].name == "xfail"
    assert by_id["sse"].marks[0].kwargs == {"reason": "broken on sse", "strict": True}
    assert by_id["in-memory"].marks == ()
    assert by_id["streamable-http"].marks == ()
    assert by_id["streamable-http-stateless"].marks == ()


def test_compute_cells_wildcard_known_failure_marks_every_cell() -> None:
    """A known failure with both transport and spec_version unset marks every emitted cell as strict xfail."""
    cells = compute_cells([_req(known_failures=(KnownFailure(note="all broken"),))], spec_versions=("2025-11-25",))
    assert len(cells) == 4
    assert all(c.marks[0].name == "xfail" for c in cells)
    assert all(c.marks[0].kwargs == {"reason": "all broken", "strict": True} for c in cells)


def test_compute_cells_ignores_transports_field() -> None:
    """Requirement.transports is descriptive metadata only and does not filter the cell grid."""
    cells = compute_cells([_req(transports=("stdio",))], spec_versions=("2025-11-25",))
    assert [c.id for c in cells] == list(CONNECTABLE_TRANSPORTS)


def test_cell_id_omits_version_when_single_spec_version() -> None:
    """With a single-version axis the cell id is just the transport name."""
    assert cell_id("sse", "2025-11-25", spec_versions=("2025-11-25",)) == "sse"


def test_cell_id_appends_version_when_multiple_spec_versions() -> None:
    """With more than one active spec version the cell id gains a -<version> suffix."""
    assert cell_id("sse", "2025-11-25", spec_versions=("2025-11-25", "2026-07-28")) == "sse-2025-11-25"
