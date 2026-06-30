"""Construction-time tests for `mcp.client.extension`; no session is ever opened."""

from dataclasses import FrozenInstanceError
from typing import Any, Literal, cast

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
    result_type: Literal["task"] = "task"
    task_id: str = "t-1"


class _UntaggedResult(Result):
    """No `result_type` field at all."""


class _PlainStringTagResult(Result):
    result_type: str = "task"


class _OtherTagResult(Result):
    result_type: Literal["other"] = "other"


class _ClaimedCallToolResult(CallToolResult):
    """A core-result subclass; rejected as a claim model regardless of its tag."""


class _ClaimedInputRequiredResult(InputRequiredResult):
    """A core-result subclass; rejected as a claim model regardless of its tag."""


async def _resolve(result: Result, ctx: ClaimContext) -> CallToolResult:
    raise NotImplementedError


def _claim(model: type[Result] = _TaskResult, **kwargs: Any) -> ResultClaim[Result]:
    return ResultClaim(result_type="task", model=model, resolve=_resolve, **kwargs)


def test_claim_with_literal_discriminated_model_constructs() -> None:
    """SDK-defined: a model tagged with the claimed Literal constructs, defaulting to `tools/call` everywhere."""
    claim = ResultClaim(result_type="task", model=_TaskResult, resolve=_resolve)

    assert claim.result_type == "task"
    assert claim.model is _TaskResult
    assert claim.resolve is _resolve
    assert claim.method == "tools/call"
    assert claim.protocol_versions is None


def test_claim_accepts_modern_protocol_versions() -> None:
    """SDK-defined: a non-None `protocol_versions` subset of the modern revisions is accepted."""
    versions = frozenset(MODERN_PROTOCOL_VERSIONS)

    claim = _claim(protocol_versions=versions)

    assert claim.protocol_versions == versions


def test_claim_rejects_core_result_type_vocabulary() -> None:
    """SDK-defined: a claim cannot re-key the core tags 'complete' and 'input_required'."""
    messages: dict[str, str] = {}
    for result_type in ("complete", "input_required"):
        with pytest.raises(ValueError) as exc_info:
            ResultClaim(result_type=result_type, model=_TaskResult, resolve=_resolve)
        messages[result_type] = str(exc_info.value)

    assert messages == snapshot(
        {
            "complete": "resultType 'complete' is core protocol vocabulary",
            "input_required": "resultType 'input_required' is core protocol vocabulary",
        }
    )


@pytest.mark.parametrize("model", [_ClaimedCallToolResult, _ClaimedInputRequiredResult])
def test_claim_rejects_model_subclassing_core_result_types(model: type[Result]) -> None:
    """SDK-defined: a claim model subclassing a core result type is rejected; it would bypass claim routing."""
    with pytest.raises(ValueError) as exc_info:
        _claim(model=model)

    assert str(exc_info.value) == snapshot("claim models must not subclass core result types")


def test_claim_rejects_model_without_result_type_field() -> None:
    """SDK-defined: the claim model must declare the discriminating `result_type` field."""
    with pytest.raises(ValueError) as exc_info:
        _claim(model=_UntaggedResult)

    assert str(exc_info.value) == snapshot("_UntaggedResult.result_type must be Literal['task']")


def test_claim_rejects_plain_str_result_type_field() -> None:
    """SDK-defined: the model's `result_type` must be a Literal of the claimed tag, not a plain `str`."""
    with pytest.raises(ValueError) as exc_info:
        _claim(model=_PlainStringTagResult)

    assert str(exc_info.value) == snapshot("_PlainStringTagResult.result_type must be Literal['task']")


def test_claim_rejects_mismatched_result_type_literal() -> None:
    """SDK-defined: the model's Literal tag must equal the claim's `result_type`."""
    with pytest.raises(ValueError) as exc_info:
        _claim(model=_OtherTagResult)

    assert str(exc_info.value) == snapshot("_OtherTagResult.result_type must be Literal['task']")


class _NotAResult(BaseModel):
    result_type: Literal["plain"] = "plain"


class _ReservedAliasResult(Result):
    result_type: Literal["clash"] = "clash"
    request_state: dict[str, Any] = {}


def test_claim_rejects_model_not_subclassing_result() -> None:
    """SDK-defined: a plain BaseModel cannot be a claim model; the session returns `Result` values."""
    with pytest.raises(ValueError) as exc_info:
        ResultClaim(result_type="plain", model=cast("type[Result]", _NotAResult), resolve=_resolve)

    assert str(exc_info.value) == snapshot("_NotAResult must subclass mcp_types.Result")


def test_claim_rejects_model_aliasing_core_surface_fields() -> None:
    """SDK-defined: a field aliasing requestState or inputRequests would fail core pre-validation."""
    with pytest.raises(ValueError) as exc_info:
        ResultClaim(result_type="clash", model=_ReservedAliasResult, resolve=_resolve)

    assert str(exc_info.value) == snapshot(
        "_ReservedAliasResult.request_state aliases 'requestState', a typed field of the core "
        "result surface; a colliding value would fail core validation before the claim adapter runs"
    )


def test_claim_rejects_method_outside_the_closed_verb_set() -> None:
    """SDK-defined: claims attach to `tools/call` only, even for values that dodge the static Literal gate."""
    with pytest.raises(ValueError) as exc_info:
        _claim(method=cast("Literal['tools/call']", "prompts/get"))

    assert str(exc_info.value) == snapshot("claims attach to ['tools/call'] only; got method 'prompts/get'")


def test_claim_rejects_empty_protocol_versions() -> None:
    """SDK-defined: an empty version set is rejected; `None` is the spelling for every modern version."""
    with pytest.raises(ValueError) as exc_info:
        _claim(protocol_versions=frozenset())

    assert str(exc_info.value) == snapshot("empty protocol_versions could never activate; use None for all")


def test_claim_rejects_non_modern_protocol_versions() -> None:
    """SDK-defined: a non-None version set must be a subset of the modern protocol revisions."""
    messages: list[str] = []
    for versions in (
        frozenset({"2025-11-25"}),
        frozenset({"2026-07-28", "2025-11-25"}),
        frozenset({"never-a-version"}),
    ):
        with pytest.raises(ValueError) as exc_info:
            _claim(protocol_versions=versions)
        messages.append(str(exc_info.value))

    assert messages == snapshot(
        [
            "protocol_versions ['2025-11-25'] are not modern protocol revisions; claimed shapes "
            "cannot be delivered on a legacy wire (None means every modern version)",
            "protocol_versions ['2025-11-25'] are not modern protocol revisions; claimed shapes "
            "cannot be delivered on a legacy wire (None means every modern version)",
            "protocol_versions ['never-a-version'] are not modern protocol revisions; claimed shapes "
            "cannot be delivered on a legacy wire (None means every modern version)",
        ]
    )


def test_result_claim_is_frozen() -> None:
    """SDK-defined: claims are immutable; mutating one after construction raises."""
    claim = _claim()

    with pytest.raises(FrozenInstanceError):
        setattr(claim, "result_type", "other")  # direct assignment is also a type error


class _TaskNotificationParams(BaseModel):
    task_id: str


async def _on_task(params: _TaskNotificationParams) -> None:
    raise NotImplementedError


def test_notification_binding_constructs() -> None:
    """SDK-defined: a binding is a bare declaration with no construction-time validation."""
    binding = NotificationBinding(method="notifications/tasks", params_type=_TaskNotificationParams, handler=_on_task)

    assert binding.method == "notifications/tasks"
    assert binding.params_type is _TaskNotificationParams
    assert binding.handler is _on_task


def test_notification_binding_accepts_core_known_method() -> None:
    """SDK-defined: deliberately no spec-table check at construction, so packages survive core adopting a method."""
    binding = NotificationBinding(
        method="notifications/progress", params_type=_TaskNotificationParams, handler=_on_task
    )

    assert binding.method == "notifications/progress"


def test_notification_binding_is_frozen() -> None:
    """SDK-defined: bindings are immutable; mutating one after construction raises."""
    binding = NotificationBinding(method="notifications/tasks", params_type=_TaskNotificationParams, handler=_on_task)

    with pytest.raises(FrozenInstanceError):
        setattr(binding, "method", "notifications/other")  # direct assignment is also a type error


def test_extension_defaults_advertise_nothing() -> None:
    """SDK-defined: a minimal subclass advertises empty settings, no claims, and no bindings."""

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
    """Spec `_meta` key grammar: conformant `vendor-prefix/name` identifiers are accepted."""
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
    """SDK-defined: the SEP-2133 `vendor-prefix/name` grammar is enforced the moment the subclass is defined."""
    with pytest.raises(TypeError):
        type("_BadExt", (ClientExtension,), {"identifier": identifier})


def test_subclass_without_identifier_allowed_at_definition() -> None:
    """SDK-defined: a subclass with no class-level `identifier` is allowed; validation waits for consumption."""

    class _AbstractishExt(ClientExtension):
        """Intermediate base; concrete subclasses supply the identifier."""

    class _ConcreteExt(_AbstractishExt):
        identifier = "com.example/concrete"

    assert _ConcreteExt.identifier == "com.example/concrete"


def test_advertise_serves_captured_settings() -> None:
    """SDK-defined: `advertise()` returns an ad-only extension serving the captured settings."""
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
    """SDK-defined: `advertise()` validates the identifier eagerly, at the call site."""
    with pytest.raises(TypeError):
        advertise(identifier)
