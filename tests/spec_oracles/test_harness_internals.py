"""Edge-case pins for the burn-down harness's own helpers.

The comparison harness is test infrastructure: its loader validation, type
algebra, and gap machinery decide what the burn-down gate accepts. These tests
pin the defensive branches directly with synthetic inputs so a regression in
the harness itself cannot silently weaken the gate.
"""

from __future__ import annotations

import json
import types
from pathlib import Path
from typing import Any

import pytest
from pydantic import Base64Str, BaseModel
from typing_extensions import TypeAliasType

from tests.spec_oracles import _harness as h
from tests.spec_oracles.test_burndown import _format

# --- load_allowlist validation -----------------------------------------------


def _write_allowlist(path: Path, entries: list[dict[str, Any]]) -> Path:
    target = path / "allowlist.json"
    target.write_text(json.dumps({"entries": entries}))
    return target


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


def test_loader_rejects_id_not_matching_its_parts(tmp_path: Path) -> None:
    path = _write_allowlist(tmp_path, [_raw_entry(id="v2026_07_28/Bar#SPEC-TYPE-MISSING")])
    with pytest.raises(ValueError, match="does not match its parts"):
        h.load_allowlist(path)


def test_loader_rejects_unknown_category(tmp_path: Path) -> None:
    path = _write_allowlist(tmp_path, [_raw_entry(category="wontfix")])
    with pytest.raises(ValueError, match="unknown category"):
        h.load_allowlist(path)


def test_loader_rejects_soft_checks(tmp_path: Path) -> None:
    # Soft findings never fail the gate, so allowlisting one is a mistake.
    path = _write_allowlist(tmp_path, [_raw_entry(id="v2026_07_28/Foo#TYPE-WIDER", check="TYPE-WIDER")])
    with pytest.raises(ValueError, match="only hard findings"):
        h.load_allowlist(path)


def test_loader_rejects_gap_check_without_gap_category(tmp_path: Path) -> None:
    path = _write_allowlist(tmp_path, [_raw_entry(id="v2026_07_28/Foo#VACUOUS-SCHEMA", check="VACUOUS-SCHEMA")])
    with pytest.raises(ValueError, match="must be category schema-gap"):
        h.load_allowlist(path)


def test_loader_rejects_gap_category_on_hard_check(tmp_path: Path) -> None:
    path = _write_allowlist(tmp_path, [_raw_entry(category="schema-gap")])
    with pytest.raises(ValueError, match="must use a gap pseudo-check"):
        h.load_allowlist(path)


def test_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = _write_allowlist(tmp_path, [_raw_entry(), _raw_entry()])
    with pytest.raises(ValueError, match="duplicate allowlist ids"):
        h.load_allowlist(path)


# --- sig: annotation canonicalization ----------------------------------------


def test_sig_canonicalizes_base64_strings() -> None:
    assert h.sig(Base64Str, sdk=False) == ("base64",)


def test_sig_marks_recursive_aliases_instead_of_recursing() -> None:
    # A self-referential alias must bottom out in a named marker rather than
    # recursing forever; the cycle check keys on the alias name.
    placeholder = TypeAliasType("Rec", int)
    rec = TypeAliasType("Rec", list[placeholder])
    assert h.sig(rec, sdk=False) == ("list", ("recursive", "Rec"))


def test_sig_collapses_union_members_with_identical_signatures() -> None:
    # An alias of list[int] and list[int] itself are distinct annotation
    # objects with the same canonical signature; the union folds to one member.
    alias = TypeAliasType("IntList", list[int])
    assert h.sig(alias | list[int], sdk=False) == ("list", ("prim", "int"))


def test_sig_treats_bare_dict_as_open_mapping() -> None:
    # The legacy bare-Dict spelling carries a dict origin with no type
    # arguments; the canonical form is an open mapping.
    bare_dict = types.GenericAlias(dict, ())
    assert h.sig(bare_dict, sdk=False) == ("dict", ("any",), ("any",))


def test_sig_marks_unknown_classes_opaque() -> None:
    class NotAModel:
        pass

    kind, detail = h.sig(NotAModel, sdk=False)
    assert kind == "opaque"
    assert detail.endswith("NotAModel")


# --- the optionality-stripping helper -----------------------------------------


def test_strip_optional_null_keeps_plain_null_for_null_only_unions() -> None:
    assert h._strip_optional_null(("union", frozenset({("null",)}))) == ("null",)


# --- compat: the type algebra's primitive relations ----------------------------


@pytest.mark.parametrize(
    ("spec", "sdk", "expected"),
    [
        # An Any on the spec side means the oracle accepts everything; any
        # concrete SDK annotation is narrower.
        (("any",), ("prim", "int"), "sdk_narrower"),
        # Numeric widening is directional.
        (("prim", "int"), ("prim", "float"), "sdk_wider"),
        (("prim", "float"), ("prim", "int"), "sdk_narrower"),
        (("prim", "str"), ("prim", "bool"), "incomparable"),
        # Literal sets compare by inclusion.
        (("lit", frozenset({"a"})), ("lit", frozenset({"a", "b"})), "sdk_wider"),
        (("lit", frozenset({"a", "b"})), ("lit", frozenset({"a"})), "sdk_narrower"),
        # A union member rejected without any incomparable verdict keeps the
        # overall relation at narrower while later members are still walked.
        (
            ("union", frozenset({("prim", "float"), ("prim", "int")})),
            ("prim", "int"),
            "sdk_narrower",
        ),
        # A Literal against its base primitive widens; against a different
        # primitive the algebra cannot relate them.
        (("lit", frozenset({"a", "b"})), ("prim", "str"), "sdk_wider"),
        (("lit", frozenset({"a"})), ("prim", "int"), "incomparable"),
        (("prim", "str"), ("lit", frozenset({"a"})), "sdk_narrower"),
        (("prim", "int"), ("lit", frozenset({"a"})), "incomparable"),
        # Base64-constrained strings sit inside plain strings.
        (("base64",), ("prim", "str"), "sdk_wider"),
        (("base64",), ("prim", "int"), "incomparable"),
        (("prim", "str"), ("base64",), "sdk_narrower"),
        (("prim", "int"), ("base64",), "incomparable"),
        # File URLs sit inside general URLs, and URLs inside plain strings.
        (("url", "any"), ("url", "file"), "sdk_narrower"),
        (("url", "file"), ("url", "any"), "sdk_wider"),
        (("url", "any"), ("prim", "str"), "sdk_wider"),
        (("prim", "str"), ("url", "any"), "sdk_narrower"),
        # Containers compare element-wise; dicts take the worst of key/value.
        (("list", ("prim", "int")), ("list", ("prim", "float")), "sdk_wider"),
        (
            ("dict", ("prim", "str"), ("prim", "float")),
            ("dict", ("prim", "str"), ("prim", "int")),
            "sdk_narrower",
        ),
        # Differently named models are out of the algebra's reach.
        (("model", "Foo"), ("model", "Bar"), "incomparable"),
    ],
)
def test_compat_primitive_relations(spec: h.Sig, sdk: h.Sig, expected: str) -> None:
    assert h.compat(spec, sdk) == expected


# --- field comparison: schema-gap paths are skipped ----------------------------


class _SpecModel(BaseModel):
    value: int


class _SdkModel(BaseModel):
    value: str


def test_field_comparison_skips_gap_paths() -> None:
    gap: h.GapPaths = frozenset({("v2026_07_28", "Synthetic", "value")})
    without_gap = h._compare_models("v2026_07_28", "Synthetic", _SpecModel, _SdkModel, frozenset())
    with_gap = h._compare_models("v2026_07_28", "Synthetic", _SpecModel, _SdkModel, gap)
    assert any(f.check == "TYPE-INCOMPARABLE" for f in without_gap)
    assert with_gap == []


# --- aggregated checks: alias-only pairings carry no field information ---------


def test_phantom_field_check_skips_names_paired_only_to_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    # Cursor is a plain alias def: a model paired only to alias defs has no
    # oracle field set to compare against, so no field findings are emitted.
    monkeypatch.setattr(h, "_sdk_public_names", lambda: ["CallToolResult"])
    monkeypatch.setattr(h, "_sdk_to_oracle_defs", lambda: {"CallToolResult": [("v2025_03_26", "Cursor")]})
    assert h.aggregated_findings() == []


# --- schema_gap_applies: liveness probes for gap exemptions --------------------


def _gap_entry(check: str, name: str, field: str | None = None) -> h.AllowlistEntry:
    field_part = f".{field}" if field is not None else ""
    return h.AllowlistEntry(
        id=f"ext_tasks/{name}{field_part}#{check}",
        check=check,
        oracle="ext_tasks",
        name=name,
        field=field,
        category="schema-gap",
        reason="synthetic",
        track=None,
    )


def test_gap_entry_for_a_vanished_def_is_stale() -> None:
    assert not h.schema_gap_applies(_gap_entry("VACUOUS-SCHEMA", "NoSuchDef"))


def test_required_unverifiable_needs_a_model_def() -> None:
    # InputRequest resolves to a plain alias, not a model, so the lost
    # `required`-array exemption cannot apply to it.
    assert not h.schema_gap_applies(_gap_entry("REQUIRED-UNVERIFIABLE", "InputRequest"))


def test_schema_gap_probe_rejects_non_gap_checks() -> None:
    with pytest.raises(ValueError, match="not a schema-gap pseudo-check"):
        h.schema_gap_applies(_gap_entry("SPEC-TYPE-MISSING", "Task"))


# --- closure and Any-detection helpers -----------------------------------------


class _Leaf(BaseModel):
    name: str


def test_closure_walks_through_type_aliases() -> None:
    alias = TypeAliasType("LeafAlias", _Leaf)
    seen: set[type[BaseModel]] = set()
    h._closure_models(alias, seen)
    assert seen == {_Leaf}


@pytest.mark.parametrize(
    ("signature", "expected"),
    [
        (("union", frozenset({("any",)})), True),
        (("union", frozenset({("prim", "str")})), False),
        (("list", ("any",)), True),
        (("list", ("prim", "int")), False),
    ],
)
def test_contains_any_descends_into_unions_and_lists(signature: h.Sig, expected: bool) -> None:
    assert h._contains_any(signature) is expected


# --- the gate's failure formatter ----------------------------------------------


def test_failure_formatter_lists_finding_ids_with_details() -> None:
    finding = h.Finding(check="SPEC-TYPE-MISSING", oracle="v2026_07_28", name="Foo", field=None, detail="synthetic")
    text = _format((finding,))
    assert "v2026_07_28/Foo#SPEC-TYPE-MISSING" in text
    assert "synthetic" in text
