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

import pytest

from tests.interaction._requirements import REQUIREMENTS, Requirement, covered_by, requirement

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


def test_unknown_requirement_id_is_rejected() -> None:
    """Marking a test with an ID that is not in the manifest fails at decoration time."""
    with pytest.raises(KeyError, match="Unknown requirement id 'tools:call:does-not-exist'"):
        requirement("tools:call:does-not-exist")


def test_invalid_requirement_source_is_rejected() -> None:
    """A requirement whose source is not a spec URL, 'sdk', or an issue reference fails at construction."""
    with pytest.raises(ValueError, match="source must be a specification URL"):
        Requirement(source="https://example.com/not-the-spec", behavior="Never constructed.")
