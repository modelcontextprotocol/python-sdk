"""Engine-internal behaviors of `mcp.types._shaping` that the shipped fact
blocks cannot exercise from the public surface.

The engine interprets row data; a few of its documented rules are independent
of any particular block's contents (injection owner resolution is row-order
independent; the unknown-tag refinement ignores error locations that do not
resolve in the input). These are pinned here against hand-built rows and
synthetic validation errors.
"""

from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_core import InitErrorDetails

from mcp.types import CallToolResult, InputRequiredResult, Result, TextContent
from mcp.types._shaping import _locate, _refine_unknown_tag, _union_tags, serialize
from mcp.types._version_facts import Inject, VersionFacts


def facts_with_injections(*rows: Inject) -> VersionFacts:
    return VersionFacts(
        version="2026-07-28",
        client_request_methods=frozenset(),
        client_notification_methods=frozenset(),
        server_request_methods=frozenset(),
        server_notification_methods=frozenset(),
        strip_on_emit=(),
        inject_on_emit=rows,
        refuse_on_emit=(),
        meta_required_methods=frozenset(),
        recognized_result_types=frozenset(),
    )


def test_injection_owner_resolution_is_row_order_independent() -> None:
    """When a base-class row and a subclass row name the same wire field, the
    most-derived owner wins no matter which row is listed first."""
    facts = facts_with_injections(
        Inject(InputRequiredResult, "resultType", "input_required"),
        Inject(Result, "resultType", "complete"),
    )
    body = serialize(InputRequiredResult(request_state="s"), "2026-07-28", facts)
    assert body["resultType"] == "input_required"
    body = serialize(CallToolResult(content=[TextContent(text="hi")]), "2026-07-28", facts)
    assert body["resultType"] == "complete"


def test_refinement_skips_error_locations_that_do_not_resolve() -> None:
    """An error location that does not index into the input (here: positions in
    an empty list) names nothing the refinement could classify; such lines are
    ignored and the original error would surface unchanged."""
    lines = [
        # A tag-mismatch line whose fragment cannot be located.
        InitErrorDetails(type="literal_error", loc=("other", 5, "type"), input="x", ctx={"expected": "'text'"}),
        # A locatable tag-mismatch line, but no arm label resolves to a tag.
        InitErrorDetails(type="literal_error", loc=("frag", "type"), input="zzz", ctx={"expected": "'text'"}),
        # A non-locatable structural line, skipped while gathering arm labels.
        InitErrorDetails(type="missing", loc=("other", 3, "field"), input={}),
    ]
    error = ValidationError.from_exception_data("Test", lines)
    assert _refine_unknown_tag(error, {"frag": {"type": "zzz"}, "other": []}) is None


@pytest.mark.parametrize("loc", [("items", 0), ("items", 5)])
def test_locate_returns_none_for_a_position_outside_the_input(loc: tuple[str | int, ...]) -> None:
    data: dict[str, Any] = {"items": {}}
    assert _locate(loc, data) is None


def test_union_tags_reads_only_classes_with_a_type_literal() -> None:
    """Arm labels that name no model class, or a class without a literal type
    field, contribute no tags."""
    assert _union_tags({"TextContent", "EmptyResult", "NotARealClass"}) == frozenset({"text"})
