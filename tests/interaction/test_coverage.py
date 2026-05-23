"""Enforces the contract between the requirements manifest and the test suite.

Every non-deferred entry in :data:`REQUIREMENTS` must be exercised by at least one test, and every
`@requirement(...)` mark must reference a manifest entry. Test modules are imported directly
(rather than relying on pytest collection) so the check holds even when only this file is run.
"""

import importlib
from pathlib import Path

import pytest

from tests.interaction._requirements import REQUIREMENTS, covered_by, requirement

_SUITE_ROOT = Path(__file__).parent


def _import_all_test_modules() -> None:
    """Import every test module in the suite so their `@requirement` decorators register."""
    for path in sorted(_SUITE_ROOT.rglob("test_*.py")):
        relative = path.relative_to(_SUITE_ROOT).with_suffix("")
        importlib.import_module(f"{__package__}.{'.'.join(relative.parts)}")


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


def test_unknown_requirement_id_is_rejected() -> None:
    """Marking a test with an ID that is not in the manifest fails at decoration time."""
    with pytest.raises(KeyError, match="Unknown requirement id 'tools:call:does-not-exist'"):
        requirement("tools:call:does-not-exist")
