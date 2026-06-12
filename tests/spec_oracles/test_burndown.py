"""Burn-down gate: generated spec oracles vs the SDK's curated types.

Fails on (a) any hard finding not in burndown_allowlist.json, and (b) any
allowlist entry that no longer fires (stale entry - remove it). Together the
two directions make the allowlist a burn-down list: implementing a type or
field forces the corresponding entries out of the file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import GenericAlias, ModuleType
from typing import Any

import pytest
from pydantic import Base64Str, BaseModel
from typing_extensions import TypeAliasType

from tests.spec_oracles import _harness as h


def _alias(name: str, value: Any) -> TypeAliasType:
    """Build an alias object as plain test data (not a module type alias)."""
    return TypeAliasType(name, value)


@pytest.fixture(scope="module")
def entries() -> list[h.AllowlistEntry]:
    return h.load_allowlist()


@pytest.fixture(scope="module")
def evaluation(entries: list[h.AllowlistEntry]) -> h.Evaluation:
    findings = h.all_findings()
    return h.evaluate(findings, entries)


def _format(findings: tuple[h.Finding, ...]) -> str:
    lines = [f"  {f.id}\n      {f.detail}" for f in findings]
    return "\n".join(lines)


@pytest.mark.parametrize("oracle", [*h.ORACLE_MODULES, "sdk"])
def test_no_unallowlisted_hard_findings(oracle: str, evaluation: h.Evaluation) -> None:
    new = tuple(f for f in evaluation.new_hard if f.oracle == oracle)
    formatted = _format(new)
    assert not new, (
        f"{len(new)} hard finding(s) for {oracle} not in burndown_allowlist.json - "
        f"either fix the SDK divergence or add a categorized entry:\n{formatted}"
    )


def test_no_stale_allowlist_entries(evaluation: h.Evaluation) -> None:
    stale = evaluation.stale_entries
    assert not stale, (
        f"{len(stale)} allowlist entr(ies) no longer fire - the divergence was fixed, "
        "so remove them from burndown_allowlist.json (the burn-down ratchet):\n"
        + "\n".join(f"  {e.id} ({e.category})" for e in stale)
    )


def test_allowlist_entries_well_formed(entries: list[h.AllowlistEntry]) -> None:
    # load_allowlist already validates ids, categories, checks, and uniqueness;
    # this pins the invariants the loader enforces on the committed file.
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


def _raw_entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": "v2026_07_28/Foo#SPEC-TYPE-MISSING",
        "check": "SPEC-TYPE-MISSING",
        "oracle": "v2026_07_28",
        "name": "Foo",
        "category": "not-yet-implemented",
        "reason": "synthetic",
    }
    entry.update(overrides)
    return entry


def _write_allowlist(tmp_path: Path, entries: list[dict[str, Any]]) -> Path:
    path = tmp_path / "allowlist.json"
    path.write_text(json.dumps({"entries": entries}))
    return path


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        pytest.param({"name": "Bar"}, "does not match its parts", id="id-parts-mismatch"),
        pytest.param({"category": "wontfix"}, "unknown category", id="unknown-category"),
        pytest.param(
            {"id": "v2026_07_28/Foo#TYPE-WIDER", "check": "TYPE-WIDER"},
            "only hard findings",
            id="soft-check",
        ),
        pytest.param({"reason": "   "}, "empty reason", id="blank-reason"),
    ],
)
def test_load_allowlist_rejects_malformed_entries(tmp_path: Path, overrides: dict[str, Any], match: str) -> None:
    path = _write_allowlist(tmp_path, [_raw_entry(**overrides)])
    with pytest.raises(ValueError, match=match):
        h.load_allowlist(path)


def test_load_allowlist_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = _write_allowlist(tmp_path, [_raw_entry(), _raw_entry()])
    with pytest.raises(ValueError, match="duplicate allowlist ids"):
        h.load_allowlist(path)


def test_sdk_lookup_returns_none_for_an_unknown_name() -> None:
    assert h.sdk_lookup("NoSuchSdkName") is None


def test_sig_canonicalizes_the_less_common_annotation_shapes() -> None:
    assert h.sig(Base64Str, sdk=False) == ("base64",)
    assert h.sig(bytes, sdk=False) == ("opaque", "builtins.bytes")
    # A dict generic with no parameters (the oracles' JSONObject spellings
    # vary by version, including unparametrized forms).
    assert h.sig(GenericAlias(dict, ()), sdk=False) == ("dict", ("any",), ("any",))


def test_sig_marks_a_revisited_alias_name_as_recursive() -> None:
    # Two alias objects sharing one name model a self-referential alias
    # (the 2026-07-28 schema's JSONValue group): the second visit to the name
    # must terminate instead of recursing forever.
    inner = _alias("Recursive", str)
    outer = _alias("Recursive", inner | int)
    assert h.sig(outer, sdk=False) == ("union", frozenset({("recursive", "Recursive"), ("prim", "int")}))


def test_sig_collapses_a_union_whose_members_canonicalize_alike() -> None:
    str_alias = _alias("StrAlias", str)
    assert h.sig(str_alias | str, sdk=False) == ("prim", "str")


def test_strip_optional_null_on_a_null_only_union() -> None:
    assert h._strip_optional_null(("union", frozenset({("null",)}))) == ("null",)


@pytest.mark.parametrize(
    ("spec", "sdk", "expected"),
    [
        pytest.param(("any",), ("prim", "str"), "sdk_narrower", id="spec-any"),
        pytest.param(("lit", frozenset({"a"})), ("lit", frozenset({"a", "b"})), "sdk_wider", id="lit-subset"),
        pytest.param(("lit", frozenset({"a", "b"})), ("lit", frozenset({"a"})), "sdk_narrower", id="lit-superset"),
        pytest.param(("lit", frozenset({"a"})), ("lit", frozenset({"b"})), "incomparable", id="lit-disjoint"),
        pytest.param(("lit", frozenset({"a"})), ("prim", "str"), "sdk_wider", id="lit-vs-base-prim"),
        pytest.param(("lit", frozenset({"a"})), ("prim", "int"), "incomparable", id="lit-vs-other-prim"),
        pytest.param(("prim", "str"), ("lit", frozenset({"a"})), "sdk_narrower", id="prim-vs-base-lit"),
        pytest.param(("prim", "int"), ("lit", frozenset({"a"})), "incomparable", id="prim-vs-other-lit"),
        pytest.param(("base64",), ("prim", "str"), "sdk_wider", id="base64-vs-str"),
        pytest.param(("base64",), ("prim", "int"), "incomparable", id="base64-vs-other"),
        pytest.param(("prim", "str"), ("base64",), "sdk_narrower", id="str-vs-base64"),
        pytest.param(("prim", "int"), ("base64",), "incomparable", id="other-vs-base64"),
        pytest.param(("prim", "int"), ("prim", "float"), "sdk_wider", id="int-vs-float"),
        pytest.param(("prim", "float"), ("prim", "int"), "sdk_narrower", id="float-vs-int"),
        pytest.param(("prim", "str"), ("url", "any"), "sdk_narrower", id="str-vs-url"),
    ],
)
def test_compat_relates_non_union_signatures(spec: h.Sig, sdk: h.Sig, expected: h.Compat) -> None:
    assert h.compat(spec, sdk) == expected


def test_compat_union_member_rejected_without_ambiguity_is_narrower() -> None:
    # One spec member is accepted (the int literal fits the int prim), the
    # other is provably narrowed (float does not fit int) - no member is
    # merely incomparable, so the verdict is a clean narrowing.
    spec = ("union", frozenset({("prim", "float"), ("lit", frozenset({1}))}))
    assert h.compat(spec, ("prim", "int")) == "sdk_narrower"


def test_compat_union_member_with_no_relatable_counterpart_is_incomparable() -> None:
    spec = ("union", frozenset({("prim", "str"), ("prim", "int")}))
    assert h.compat(spec, ("prim", "int")) == "incomparable"


def test_compare_oracle_reports_unpaired_defs_and_sdk_only_required_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnpairedSpecType(BaseModel):
        pass

    class Icon(BaseModel):
        # Deliberately lacks the SDK Icon's required `src` field.
        pass

    fake = ModuleType("tests.spec_oracles.fake_oracle")
    setattr(fake, "SPEC_DEFS", ("UnpairedSpecType", "Icon"))
    setattr(fake, "UnpairedSpecType", UnpairedSpecType)
    setattr(fake, "Icon", Icon)
    monkeypatch.setitem(sys.modules, "tests.spec_oracles.fake_oracle", fake)

    findings = h.compare_oracle("fake_oracle")

    assert [(f.check, f.name, f.field) for f in findings] == [
        ("SDK-REQUIRED-NOT-IN-SPEC", "Icon", "src"),
        ("SPEC-TYPE-MISSING", "UnpairedSpecType", None),
    ]


def test_aggregated_findings_skip_sdk_models_paired_only_to_non_model_defs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An SDK model whose only oracle counterpart is a bare alias offers no
    # field sets to compare, so the field-phantom check does not apply.
    fake = ModuleType("tests.spec_oracles.fake_oracle")
    setattr(fake, "AliasDef", str)
    monkeypatch.setitem(sys.modules, "tests.spec_oracles.fake_oracle", fake)
    monkeypatch.setattr(h, "_sdk_public_names", lambda: ["Implementation"])
    monkeypatch.setattr(h, "_sdk_to_oracle_defs", lambda: {"Implementation": [("fake_oracle", "AliasDef")]})

    assert h.aggregated_findings() == []
