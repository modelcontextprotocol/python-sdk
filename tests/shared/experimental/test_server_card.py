"""`mcp.shared.experimental.server_card`: models, validators and `resolve_remote`."""

import json
from pathlib import Path

import pytest
from inline_snapshot import snapshot
from pydantic import ValidationError

from mcp.shared.experimental.server_card import (
    SERVER_CARD_SCHEMA_URL,
    Input,
    KeyValueInput,
    Remote,
    ServerCard,
    resolve_remote,
)

FIXTURES = Path(__file__).parent / "fixtures" / "server_card"

VALID_FIXTURES = sorted((FIXTURES / "valid").glob("*.json"))
INVALID_FIXTURES = sorted(path for path in (FIXTURES / "invalid").glob("*.json") if path.name != "missing-schema.json")


def _minimal_card_data(**overrides: object) -> dict[str, object]:
    """The smallest valid card document, with per-test field overrides."""
    data: dict[str, object] = {
        "$schema": SERVER_CARD_SCHEMA_URL,
        "name": "com.example/weather",
        "version": "1.0.0",
        "description": "Hourly forecasts.",
    }
    data.update(overrides)
    return data


# -- conformance fixtures (vendored from the extension repo's examples/ServerCard) -----


@pytest.mark.parametrize("path", VALID_FIXTURES, ids=lambda p: p.name)
def test_valid_fixture_round_trips_byte_for_byte_equivalent(path: Path) -> None:
    """Spec-mandated: every valid conformance fixture parses and re-serializes to the
    same JSON document, so no field is dropped, renamed or reshaped in transit."""
    card = ServerCard.model_validate_json(path.read_bytes())
    assert json.loads(card.model_dump_json(by_alias=True, exclude_none=True)) == json.loads(path.read_text())


@pytest.mark.parametrize("path", INVALID_FIXTURES, ids=lambda p: p.name)
def test_invalid_fixture_is_rejected(path: Path) -> None:
    """Spec-mandated: the invalid conformance fixtures (bad name pattern, wrong or
    date-versioned `$schema`, missing `name`) raise `pydantic.ValidationError`."""
    with pytest.raises(ValidationError):
        ServerCard.model_validate_json(path.read_bytes())


def test_missing_schema_is_defaulted_on_ingestion() -> None:
    """SDK-defined divergence from the fixture set: the spec marks a missing `$schema`
    invalid, but the SDK deliberately defaults it so cards from lenient publishers still
    parse. Serialization always writes the canonical URL back."""
    card = ServerCard.model_validate_json((FIXTURES / "invalid" / "missing-schema.json").read_bytes())
    assert card.schema_ == SERVER_CARD_SCHEMA_URL


# -- field validators -------------------------------------------------------------------


@pytest.mark.parametrize(
    "schema_url",
    [
        "https://static.modelcontextprotocol.io/schemas/2025-11-25/server-card.schema.json",
        "https://static.modelcontextprotocol.io/schemas/v1/server.schema.json",
        "https://example.com/server-card.schema.json",
    ],
)
def test_any_schema_url_other_than_the_v1_url_is_rejected(schema_url: str) -> None:
    """Spec-mandated: `$schema` must be exactly the v1 URL. Date-versioned URLs and the
    removed registry `server.schema.json` are both invalid."""
    with pytest.raises(ValidationError):
        ServerCard.model_validate(_minimal_card_data(**{"$schema": schema_url}))


@pytest.mark.parametrize("name", ["no-slash-in-name", "ab", "a/b/c", "com.example/", "x" * 200 + "/name"])
def test_name_outside_the_namespace_slash_name_pattern_is_rejected(name: str) -> None:
    """Spec-mandated: `name` is 3-200 chars of reverse-DNS namespace, exactly one slash,
    then the server name."""
    with pytest.raises(ValidationError):
        ServerCard.model_validate(_minimal_card_data(name=name))


@pytest.mark.parametrize(
    "version", ["^1.2.3", "~1.2.3", ">=1.2.3", "<=1.2.3", ">1.2.3", "<1.2.3", "1.x", "1.*", "1.0 || 2.0"]
)
def test_version_range_syntax_is_rejected(version: str) -> None:
    """Spec-mandated (prose level, not expressible in the JSON Schema): `version` is a
    single version, never a range or wildcard."""
    with pytest.raises(ValidationError):
        ServerCard.model_validate(_minimal_card_data(version=version))


@pytest.mark.parametrize("version", ["1.0.2", "2.1.0-alpha", "2025-06-18", "not semver"])
def test_plain_version_strings_including_non_semver_are_accepted(version: str) -> None:
    """Spec-mandated: semver is a SHOULD, so plain non-semver strings still pass."""
    assert ServerCard.model_validate(_minimal_card_data(version=version)).version == version


@pytest.mark.parametrize("description", ["", "x" * 101])
def test_description_outside_1_to_100_chars_is_rejected(description: str) -> None:
    """Spec-mandated: `description` is required with 1-100 characters."""
    with pytest.raises(ValidationError):
        ServerCard.model_validate(_minimal_card_data(description=description))


def test_title_of_101_chars_is_rejected() -> None:
    """Spec-mandated: `title`, when present, is 1-100 characters."""
    with pytest.raises(ValidationError):
        ServerCard.model_validate(_minimal_card_data(title="x" * 101))


@pytest.mark.parametrize(
    "url", ["https://mcp.example.com/mcp", "http://localhost:8000/mcp", "{tenant}.example.com/mcp"]
)
def test_remote_url_accepts_http_https_and_template_prefixes(url: str) -> None:
    """Spec-mandated: `remotes[].url` starts with http://, https:// or a `{template}`."""
    assert Remote(type="streamable-http", url=url).url == url


@pytest.mark.parametrize("url", ["ftp://example.com/mcp", "mcp.example.com/mcp", ""])
def test_remote_url_rejects_other_schemes_and_bare_hosts(url: str) -> None:
    """Spec-mandated: anything not http(s) or `{template}`-prefixed fails the pattern."""
    with pytest.raises(ValidationError):
        Remote(type="streamable-http", url=url)


# -- open objects and aliasing ----------------------------------------------------------


def test_vendor_fields_and_meta_survive_a_round_trip() -> None:
    """Spec-mandated: card objects are open, so unknown vendor fields and `_meta` must
    survive parse and re-serialize."""
    data = _minimal_card_data(**{"com.example/flag": True, "_meta": {"com.example/build": 7}})
    card = ServerCard.model_validate(data)
    assert json.loads(card.model_dump_json(by_alias=True, exclude_none=True)) == data


def test_fields_populate_by_python_name_and_serialize_camel_case() -> None:
    """SDK-defined: models accept snake_case constructor names and always write the
    spec's camelCase wire names."""
    card = ServerCard(
        name="com.example/weather", version="1.0.0", description="Forecasts.", website_url="https://example.com"
    )
    dumped = json.loads(card.model_dump_json(by_alias=True, exclude_none=True))
    assert dumped["websiteUrl"] == "https://example.com"
    assert ServerCard.model_validate(dumped).website_url == "https://example.com"


# -- endpoint_urls and required_variables -----------------------------------------------


def test_endpoint_urls_returns_raw_remote_urls() -> None:
    """SDK-defined: `endpoint_urls()` is the host's dedup key, so it returns the raw
    (still templated) `remotes[].url` values."""
    card = ServerCard.model_validate(
        _minimal_card_data(
            remotes=[
                {"type": "streamable-http", "url": "https://{tenant}.example.com/mcp"},
                {"type": "sse", "url": "https://example.com/sse"},
            ]
        )
    )
    assert card.endpoint_urls() == frozenset({"https://{tenant}.example.com/mcp", "https://example.com/sse"})


def test_endpoint_urls_is_empty_without_remotes() -> None:
    """SDK-defined: a card with no `remotes` has no endpoints to key on."""
    assert ServerCard.model_validate(_minimal_card_data()).endpoint_urls() == frozenset()


def test_required_variables_keeps_only_unresolvable_required_inputs() -> None:
    """SDK-defined: a variable counts as required to prompt for only when it is
    `isRequired` with no `default` and no pre-set `value`, across the URL variables and
    each header's nested variables."""
    remote = Remote(
        type="streamable-http",
        url="https://{tenant}.example.com/{region}/mcp",
        variables={
            "tenant": Input(is_required=True),
            "region": Input(is_required=True, default="eu"),
            "theme": Input(),
        },
        headers=[
            KeyValueInput(
                name="Authorization",
                value="Bearer {token} {suffix}",
                variables={"token": Input(is_required=True), "suffix": Input(is_required=True, value="v1")},
            )
        ],
    )
    assert remote.required_variables == frozenset({"tenant", "token"})


def test_required_variables_is_empty_without_declared_variables() -> None:
    """SDK-defined: no `variables` and no `headers` means nothing to prompt for."""
    assert Remote(type="streamable-http", url="https://example.com/mcp").required_variables == frozenset()


# -- resolve_remote ---------------------------------------------------------------------


def _templated_remote() -> Remote:
    """The vendored `templated-remote.json` fixture's remote: templated URL, defaulted
    tenant, and an Authorization header with a required nested token."""
    card = ServerCard.model_validate_json((FIXTURES / "valid" / "templated-remote.json").read_bytes())
    assert card.remotes is not None
    return card.remotes[0]


def test_resolve_remote_applies_defaults_and_nested_header_variables() -> None:
    """SDK-defined: declared defaults fill the URL template and nested header variables
    fill the header value, from the spec's own full example card."""
    resolved = resolve_remote(_templated_remote(), {"token": "abc123"})
    assert resolved.type == "streamable-http"
    assert resolved.url == "https://default.example.com/mcp"
    assert resolved.headers == {"Authorization": "Bearer abc123"}


def test_resolve_remote_caller_values_override_defaults() -> None:
    """SDK-defined: a caller-supplied value beats the declared default."""
    resolved = resolve_remote(_templated_remote(), {"token": "abc123", "tenant": "acme"})
    assert resolved.url == "https://acme.example.com/mcp"


def test_resolve_remote_names_every_missing_required_variable() -> None:
    """SDK-defined: one ValueError lists all missing `isRequired` variables, so a host
    can prompt for everything at once."""
    remote = Remote(
        type="streamable-http",
        url="https://{tenant}.example.com/mcp",
        variables={"tenant": Input(is_required=True)},
        headers=[KeyValueInput(name="X-Token", is_required=True)],
    )
    with pytest.raises(ValueError) as exc_info:
        resolve_remote(remote)
    assert str(exc_info.value) == snapshot("missing required variables: X-Token, tenant")


def test_resolve_remote_supplies_header_values_by_header_name() -> None:
    """SDK-defined: a header with no pre-set `value` is itself an input, keyed by the
    header name in the caller's values."""
    remote = Remote(type="streamable-http", url="https://example.com/mcp", headers=[KeyValueInput(name="X-Token")])
    resolved = resolve_remote(remote, {"X-Token": "sekrit"})
    assert resolved.headers == {"X-Token": "sekrit"}


def test_resolve_remote_omits_optional_headers_nothing_supplies() -> None:
    """SDK-defined: an optional header with no value, default or caller entry simply
    does not appear in the resolved headers."""
    remote = Remote(type="streamable-http", url="https://example.com/mcp", headers=[KeyValueInput(name="X-Trace")])
    assert resolve_remote(remote).headers == {}


def test_resolve_remote_pre_set_value_beats_caller_value() -> None:
    """SDK-defined: a pre-set `value` is not end-user configurable, so a caller entry
    for the same name does not override it."""
    remote = Remote(
        type="streamable-http",
        url="https://{plan}.example.com/mcp",
        variables={"plan": Input(value="enterprise")},
    )
    assert resolve_remote(remote, {"plan": "free"}).url == "https://enterprise.example.com/mcp"


def test_resolve_remote_rejects_a_value_outside_declared_choices() -> None:
    """SDK-defined: when an input declares `choices`, any other value is an error."""
    remote = Remote(
        type="streamable-http",
        url="https://{region}.example.com/mcp",
        variables={"region": Input(choices=["eu", "us"])},
    )
    with pytest.raises(ValueError) as exc_info:
        resolve_remote(remote, {"region": "mars"})
    assert str(exc_info.value) == snapshot("values outside declared choices: region='mars' (choices: ['eu', 'us'])")


def test_resolve_remote_rejects_a_header_value_outside_declared_choices() -> None:
    """SDK-defined: `choices` on the header input itself constrains the header value."""
    remote = Remote(
        type="streamable-http",
        url="https://example.com/mcp",
        headers=[KeyValueInput(name="X-Mode", choices=["fast", "safe"])],
    )
    with pytest.raises(ValueError) as exc_info:
        resolve_remote(remote, {"X-Mode": "wild"})
    assert str(exc_info.value) == snapshot("values outside declared choices: X-Mode='wild' (choices: ['fast', 'safe'])")


def test_resolve_remote_rejects_a_still_templated_result() -> None:
    """SDK-defined: a `{placeholder}` that no declared variable and no caller value
    resolves is an error, never silently passed through."""
    remote = Remote(type="streamable-http", url="https://{tenant}.example.com/mcp")
    with pytest.raises(ValueError) as exc_info:
        resolve_remote(remote)
    assert str(exc_info.value) == snapshot("unresolved template variables: tenant")


def test_resolve_remote_rejects_a_non_http_resolved_url() -> None:
    """SDK-defined: template substitution must produce an http(s) URL to connect to."""
    remote = Remote(
        type="streamable-http",
        url="{scheme}example.com/mcp",
        variables={"scheme": Input(default="ftp://")},
    )
    with pytest.raises(ValueError) as exc_info:
        resolve_remote(remote)
    assert str(exc_info.value) == snapshot("resolved remote URL must be http(s), got 'ftp://example.com/mcp'")


def test_resolve_remote_skips_optional_variables_nothing_supplies() -> None:
    """SDK-defined: an optional declared variable with no value, default or caller entry
    is simply left out of the substitution mapping."""
    remote = Remote(type="streamable-http", url="https://example.com/mcp", variables={"theme": Input()})
    assert resolve_remote(remote).url == "https://example.com/mcp"
