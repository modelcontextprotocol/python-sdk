"""Tests for the client extension vocabulary (`mcp.client.extension`).

Everything here is construction-time: claims, notification bindings, the
`ClientExtension` base class, and the `advertise()` factory. No session or
client is ever opened — the classes are pure declarations, and every
validation rule fires before an instance exists.
"""

from dataclasses import FrozenInstanceError
from typing import Any, Literal

import pytest
from inline_snapshot import snapshot
from mcp_types import CallToolResult, InputRequiredResult, Result
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import BaseModel

from mcp.client.extension import (
    ClaimContext,
    ClientExtension,
    NotificationBinding,
    ResultClaim,
    advertise,
)


class _TaskResult(Result):
    """A well-formed claimed shape: `result_type` is a Literal of the claimed tag."""

    result_type: Literal["task"] = "task"
    task_id: str = "t-1"


class _UntaggedResult(Result):
    """No `result_type` field at all."""


class _PlainStringTagResult(Result):
    """`result_type` declared as a plain `str`, not a Literal."""

    result_type: str = "task"


class _OtherTagResult(Result):
    """`result_type` is a Literal of a tag other than the one claimed."""

    result_type: Literal["other"] = "other"


class _ClaimedCallToolResult(CallToolResult):
    """A core-result subclass; rejected as a claim model regardless of its tag."""


class _ClaimedInputRequiredResult(InputRequiredResult):
    """A core-result subclass; rejected as a claim model regardless of its tag."""


async def _resolve(result: Result, ctx: ClaimContext) -> CallToolResult:
    raise NotImplementedError  # construction-only tests never drive a claim


def _claim(model: type[Result] = _TaskResult, **kwargs: Any) -> ResultClaim[Result]:
    return ResultClaim(result_type="task", model=model, resolve=_resolve, **kwargs)


# ── ResultClaim construction ────────────────────────────────────────────────


def test_claim_with_literal_discriminated_model_constructs() -> None:
    """SDK-defined: a claim whose model carries `result_type: Literal[<claimed tag>]`
    constructs, defaulting to the `tools/call` verb at every modern version."""
    claim = ResultClaim(result_type="task", model=_TaskResult, resolve=_resolve)

    assert claim.result_type == "task"
    assert claim.model is _TaskResult
    assert claim.resolve is _resolve
    assert claim.method == "tools/call"
    assert claim.protocol_versions is None


def test_claim_accepts_modern_protocol_versions() -> None:
    """SDK-defined: a non-None `protocol_versions` is accepted when it is a subset of
    the modern protocol revisions."""
    versions = frozenset(MODERN_PROTOCOL_VERSIONS)

    claim = _claim(protocol_versions=versions)

    assert claim.protocol_versions == versions


@pytest.mark.parametrize("result_type", ["complete", "input_required"])
def test_claim_rejects_core_result_type_vocabulary(result_type: str) -> None:
    """SDK-defined: "complete" and "input_required" are core protocol vocabulary —
    a claim cannot re-key the shapes the session itself routes on."""
    with pytest.raises(ValueError, match="core protocol vocabulary"):
        ResultClaim(result_type=result_type, model=_TaskResult, resolve=_resolve)


@pytest.mark.parametrize("model", [_ClaimedCallToolResult, _ClaimedInputRequiredResult])
def test_claim_rejects_model_subclassing_core_result_types(model: type[Result]) -> None:
    """SDK-defined: a claim model subclassing `CallToolResult` or `InputRequiredResult`
    would satisfy the session's isinstance branches and bypass claim routing."""
    with pytest.raises(ValueError, match="must not subclass core result types"):
        _claim(model=model)


def test_claim_rejects_model_without_result_type_field() -> None:
    """SDK-defined: the claim model must declare the discriminating `result_type`
    field; without it the claimed shape could never be routed."""
    with pytest.raises(ValueError) as exc_info:
        _claim(model=_UntaggedResult)

    assert str(exc_info.value) == snapshot("_UntaggedResult.result_type must be Literal['task']")


def test_claim_rejects_plain_str_result_type_field() -> None:
    """SDK-defined: a plain `str` tag would let one model validate any claimed shape;
    the field must be a Literal of exactly the claimed tag."""
    with pytest.raises(ValueError) as exc_info:
        _claim(model=_PlainStringTagResult)

    assert str(exc_info.value) == snapshot("_PlainStringTagResult.result_type must be Literal['task']")


def test_claim_rejects_mismatched_result_type_literal() -> None:
    """SDK-defined: the model's Literal tag must equal the claim's `result_type` —
    a mismatch would register the model under a tag it refuses to validate."""
    with pytest.raises(ValueError) as exc_info:
        _claim(model=_OtherTagResult)

    assert str(exc_info.value) == snapshot("_OtherTagResult.result_type must be Literal['task']")


def test_claim_rejects_empty_protocol_versions() -> None:
    """SDK-defined: an empty version set could never activate; `None` is the
    spelling for "every modern version"."""
    with pytest.raises(ValueError) as exc_info:
        _claim(protocol_versions=frozenset())

    assert str(exc_info.value) == snapshot("empty protocol_versions could never activate; use None for all")


@pytest.mark.parametrize(
    "versions",
    [
        frozenset({"2025-11-25"}),
        frozenset({"2026-07-28", "2025-11-25"}),
        frozenset({"never-a-version"}),
    ],
)
def test_claim_rejects_non_modern_protocol_versions(versions: frozenset[str]) -> None:
    """SDK-defined: claimed shapes cannot be delivered on a legacy wire, so a
    non-None version set must be a subset of the modern protocol revisions."""
    with pytest.raises(ValueError, match="not modern protocol revisions"):
        _claim(protocol_versions=versions)


def test_result_claim_is_frozen() -> None:
    """SDK-defined: claims are immutable declarations — mutating one after
    construction raises."""
    claim = _claim()

    with pytest.raises(FrozenInstanceError):
        setattr(claim, "result_type", "other")  # direct assignment is also a type error


# ── NotificationBinding construction ────────────────────────────────────────


class _TaskNotificationParams(BaseModel):
    task_id: str


async def _on_task(params: _TaskNotificationParams) -> None:
    raise NotImplementedError  # construction-only tests never deliver


def test_notification_binding_constructs() -> None:
    """SDK-defined: a binding is a bare declaration — wire method name, params
    model, async observer — with no construction-time validation."""
    binding = NotificationBinding(method="notifications/tasks", params_type=_TaskNotificationParams, handler=_on_task)

    assert binding.method == "notifications/tasks"
    assert binding.params_type is _TaskNotificationParams
    assert binding.handler is _on_task


def test_notification_binding_accepts_core_known_method() -> None:
    """SDK-defined: deliberately NO spec-table check at construction — bindings are
    consulted only for methods core does not know, so they are additive by
    construction, and an import-time table check would break packages whenever a
    core version adopts a method."""
    binding = NotificationBinding(
        method="notifications/progress", params_type=_TaskNotificationParams, handler=_on_task
    )

    assert binding.method == "notifications/progress"


def test_notification_binding_is_frozen() -> None:
    """SDK-defined: bindings are immutable declarations — mutating one after
    construction raises."""
    binding = NotificationBinding(method="notifications/tasks", params_type=_TaskNotificationParams, handler=_on_task)

    with pytest.raises(FrozenInstanceError):
        setattr(binding, "method", "notifications/other")  # direct assignment is also a type error


# ── ClientExtension subclassing ─────────────────────────────────────────────


def test_extension_defaults_advertise_nothing() -> None:
    """SDK-defined: a minimal subclass overrides nothing — empty settings, no
    claims, no notification bindings."""

    class _MinimalExt(ClientExtension):
        identifier = "com.example/minimal"

    ext = _MinimalExt()

    assert ext.settings() == {}
    assert ext.claims() == ()
    assert ext.notifications() == ()


@pytest.mark.parametrize(
    "identifier",
    [
        "io.modelcontextprotocol/ui",
        "com.example/my_ext",
        "com.x-y.z2/n.a-b_c",
        "example/x",
        "a/b",
        "com.example/9start",
    ],
)
def test_grammar_conformant_identifiers_accepted_at_class_definition(identifier: str) -> None:
    """Spec `_meta` key grammar: dot-separated labels (letter start, letter/digit end,
    hyphens interior), a slash, then a name that starts and ends alphanumeric."""
    cls = type("_GoodExt", (ClientExtension,), {"identifier": identifier})

    assert cls.identifier == identifier


@pytest.mark.parametrize(
    "identifier",
    [
        "noprefix",
        "-foo/bar",
        ".leading/x",
        "a..b/x",
        "foo-/x",
        "9foo/x",
        "foo/-bar",
        "foo/bar-",
        "foo/",
        "/bar",
        "foo/ba r",
        "io.modelcontextprotocol/ui\n",
        "",
        42,
    ],
)
def test_malformed_identifier_rejected_at_class_definition(identifier: Any) -> None:
    """SDK-defined: SEP-2133 requires a `vendor-prefix/name` identifier, enforced the
    moment the subclass is defined — same grammar and helper as the server side."""
    with pytest.raises(TypeError):
        type("_BadExt", (ClientExtension,), {"identifier": identifier})


def test_subclass_without_identifier_allowed_at_definition() -> None:
    """SDK-defined: a subclass that sets no class-level `identifier` (an abstract-ish
    intermediate base, or one assigning per-instance ids in `__init__`) is allowed at
    definition time; the identifier is validated when the extension is consumed."""

    class _AbstractishExt(ClientExtension):
        """Intermediate base; concrete subclasses supply the identifier."""

    class _ConcreteExt(_AbstractishExt):
        identifier = "com.example/concrete"

    assert _ConcreteExt.identifier == "com.example/concrete"


# ── advertise() factory ─────────────────────────────────────────────────────


def test_advertise_serves_captured_settings() -> None:
    """SDK-defined: `advertise()` returns an ad-only extension whose `settings()`
    override serves the captured settings."""
    ext = advertise("com.example/flags", {"enabled": True})

    assert isinstance(ext, ClientExtension)
    assert ext.identifier == "com.example/flags"
    assert ext.settings() == {"enabled": True}
    assert ext.claims() == ()
    assert ext.notifications() == ()


def test_advertise_defaults_to_empty_settings() -> None:
    """SDK-defined: omitting settings advertises the extension with an empty map."""
    ext = advertise("com.example/flags")

    assert ext.settings() == {}


@pytest.mark.parametrize("identifier", ["noprefix", "foo/", ""])
def test_advertise_validates_identifier_eagerly(identifier: str) -> None:
    """SDK-defined: `advertise()` validates the identifier at the call, not at some
    later consumption point — a bad ad-only id fails where it is written."""
    with pytest.raises(TypeError):
        advertise(identifier)
