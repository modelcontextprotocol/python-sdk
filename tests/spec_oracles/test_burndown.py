"""Burn-down gate: generated spec oracles vs the SDK's curated types.

Fails on (a) any hard finding not in burndown_allowlist.json, and (b) any
allowlist entry that no longer fires (stale entry - remove it). Together the
two directions make the allowlist a burn-down list: implementing a type or
field forces the corresponding entries out of the file.
"""

from __future__ import annotations

import pytest

from tests.spec_oracles import _harness as h


@pytest.fixture(scope="module")
def entries() -> list[h.AllowlistEntry]:
    return h.load_allowlist()


@pytest.fixture(scope="module")
def evaluation(entries: list[h.AllowlistEntry]) -> h.Evaluation:
    findings = h.all_findings(h.gap_paths(entries))
    return h.evaluate(findings, entries)


def _format(findings: tuple[h.Finding, ...]) -> str:
    lines = [f"  {f.id}\n      {f.detail}" for f in findings]
    return "\n".join(lines)


@pytest.mark.parametrize("oracle", [*h.ORACLE_MODULES, "sdk"])
def test_no_unallowlisted_hard_findings(oracle: str, evaluation: h.Evaluation) -> None:
    new = tuple(f for f in evaluation.new_hard if f.oracle == oracle)
    assert not new, (
        f"{len(new)} hard finding(s) for {oracle} not in burndown_allowlist.json - "
        f"either fix the SDK divergence or add a categorized entry:\n{_format(new)}"
    )


def test_no_stale_allowlist_entries(evaluation: h.Evaluation) -> None:
    stale = evaluation.stale_entries
    assert not stale, (
        f"{len(stale)} allowlist entr(ies) no longer fire - the divergence was fixed, "
        "so remove them from burndown_allowlist.json (the burn-down ratchet):\n"
        + "\n".join(f"  {e.id} ({e.category})" for e in stale)
    )


def test_allowlist_entries_well_formed(entries: list[h.AllowlistEntry]) -> None:
    # load_allowlist already validates ids, categories, checks, uniqueness,
    # and non-empty reasons; this pins the invariants the loader enforces.
    for entry in entries:
        assert entry.oracle in (*h.ORACLE_MODULES, "sdk")
        assert entry.reason.strip()


# --- harness unit tests (synthetic data; the ratchet must work both ways) ---


def _finding(check: str = "SPEC-TYPE-MISSING", name: str = "Foo") -> h.Finding:
    return h.Finding(check=check, oracle="v2026_07_28", name=name, field=None, detail="synthetic")


def _entry(
    check: str = "SPEC-TYPE-MISSING", name: str = "Foo", category: str = "not-yet-implemented"
) -> h.AllowlistEntry:
    return h.AllowlistEntry(
        id=f"v2026_07_28/{name}#{check}",
        check=check,
        oracle="v2026_07_28",
        name=name,
        field=None,
        category=category,
        reason="synthetic",
        track=None,
    )


def test_evaluate_flags_unallowlisted_hard_finding() -> None:
    result = h.evaluate([_finding()], [])
    assert result.new_hard == (_finding(),)
    assert result.stale_entries == ()


def test_evaluate_matches_allowlisted_finding_by_id() -> None:
    result = h.evaluate([_finding()], [_entry()])
    assert result.new_hard == ()
    assert result.stale_entries == ()
    assert result.allowlisted_hard == (_finding(),)


def test_evaluate_flags_stale_entry() -> None:
    result = h.evaluate([], [_entry()])
    assert result.stale_entries == (_entry(),)


def test_evaluate_soft_findings_never_fail() -> None:
    soft = h.Finding(check="TYPE-WIDER", oracle="v2026_07_28", name="Foo", field="bar", detail="synthetic")
    result = h.evaluate([soft], [])
    assert result.new_hard == ()
    assert result.soft == (soft,)


def test_schema_gap_entry_stays_live_while_gap_exists() -> None:
    live = h.AllowlistEntry(
        id="ext_tasks/InputRequest#VACUOUS-SCHEMA",
        check="VACUOUS-SCHEMA",
        oracle="ext_tasks",
        name="InputRequest",
        field=None,
        category="schema-gap",
        reason="synthetic",
        track=None,
    )
    assert h.schema_gap_applies(live)
    result = h.evaluate([], [live])
    assert result.stale_entries == ()


def test_schema_gap_entry_goes_stale_when_gap_is_fixed() -> None:
    # Task.taskId is a real, fully-typed site: a gap entry pointing at it must
    # be reported stale (this is what fires when a future ext-tasks pin
    # restores the lost $refs and regeneration removes the Any).
    fixed = h.AllowlistEntry(
        id="ext_tasks/Task.taskId#VACUOUS-SCHEMA",
        check="VACUOUS-SCHEMA",
        oracle="ext_tasks",
        name="Task",
        field="taskId",
        category="schema-gap",
        reason="synthetic",
        track=None,
    )
    assert not h.schema_gap_applies(fixed)
    result = h.evaluate([], [fixed])
    assert result.stale_entries == (fixed,)
