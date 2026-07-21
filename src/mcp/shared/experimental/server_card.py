"""Server Card models and pure helpers (experimental, tracks SEP-2127).

A Server Card is a static JSON document that describes a single remote MCP
server well enough for a client to discover and connect to it before any
protocol exchange. See
https://github.com/modelcontextprotocol/experimental-ext-server-card for the
authoritative schema.

Card contents are unverified and advisory. Clients MUST NOT treat them as
authoritative for security or access-control decisions, and SHOULD prefer
runtime values (`serverInfo`) whenever the two disagree.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from mcp_types import Icon
from pydantic import Field, field_validator

from mcp.shared.experimental._base import SERVER_CARD_NAME_PATTERN
from mcp.shared.experimental._base import CardModel as _CardModel

__all__ = [
    "SERVER_CARD_SCHEMA_URL",
    "SERVER_CARD_MEDIA_TYPE",
    "RESERVED_SERVER_CARD_SUFFIX",
    "Input",
    "KeyValueInput",
    "Repository",
    "Remote",
    "ServerCard",
    "ResolvedRemote",
    "resolve_remote",
]

SERVER_CARD_SCHEMA_URL: Final = "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json"
"""The only `$schema` value a v1 Server Card may carry."""

SERVER_CARD_MEDIA_TYPE: Final = "application/mcp-server-card+json"
"""Media type for Server Card documents."""

RESERVED_SERVER_CARD_SUFFIX: Final = "/server-card"
"""Path suffix the spec reserves under the streamable HTTP URL."""

_REMOTE_URL_PATTERN = r"^(https?://[^\s]+|\{[a-zA-Z_][a-zA-Z0-9_]*\}[^\s]*)$"
_TEMPLATE_VARIABLE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_VERSION_RANGE_PREFIXES = ("^", "~", ">=", "<=", ">", "<")
_VERSION_WILDCARD_SEGMENTS = frozenset({"x", "X", "*"})


class Input(_CardModel):
    """A user-suppliable value referenced by a `Remote` URL or header template."""

    description: str | None = None
    is_required: bool | None = None
    is_secret: bool | None = None
    format: Literal["string", "number", "boolean", "filepath"] | None = None
    default: str | None = None
    placeholder: str | None = None
    value: str | None = None
    choices: list[str] | None = None


class KeyValueInput(Input):
    """A named input, used for HTTP headers on a `Remote`."""

    name: str
    variables: dict[str, Input] | None = None


class Repository(_CardModel):
    """Source repository metadata for the server implementation."""

    url: str
    source: str
    subfolder: str | None = None
    id: str | None = None


class Remote(_CardModel):
    """Connection metadata for one remote transport endpoint."""

    type: Literal["streamable-http", "sse"]
    url: str = Field(pattern=_REMOTE_URL_PATTERN)
    headers: list[KeyValueInput] | None = None
    variables: dict[str, Input] | None = None
    supported_protocol_versions: list[str] | None = None

    @property
    def required_variables(self) -> frozenset[str]:
        """Template variable names a host must prompt the user for.

        Covers the URL variables and each header's nested variables, keeping
        the ones declared `isRequired` with no `default` and no pre-set
        `value`.
        """
        names: set[str] = set()
        header_variables = [header.variables for header in self.headers or []]
        for variables in [self.variables, *header_variables]:
            for name, spec in (variables or {}).items():
                if spec.is_required and spec.default is None and spec.value is None:
                    names.add(name)
        return frozenset(names)


class ServerCard(_CardModel):
    """A Server Card document (`application/mcp-server-card+json`).

    Malformed documents raise `pydantic.ValidationError` at construction or
    `model_validate*` time.
    """

    schema_: str = Field(default=SERVER_CARD_SCHEMA_URL, alias="$schema")
    name: str = Field(min_length=3, max_length=200, pattern=SERVER_CARD_NAME_PATTERN)
    version: str = Field(max_length=255)
    description: str = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, min_length=1, max_length=100)
    website_url: str | None = None
    repository: Repository | None = None
    icons: list[Icon] | None = None
    remotes: list[Remote] | None = None
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")

    @field_validator("schema_")
    @classmethod
    def _schema_url_is_the_v1_url(cls, value: str) -> str:
        if value != SERVER_CARD_SCHEMA_URL:
            raise ValueError(f"$schema must be exactly {SERVER_CARD_SCHEMA_URL!r}")
        return value

    @field_validator("version")
    @classmethod
    def _version_is_not_a_range(cls, value: str) -> str:
        # Range syntax is rejected at the prose level of the spec. It is not
        # expressible in the published JSON Schema.
        if value.startswith(_VERSION_RANGE_PREFIXES) or "||" in value:
            raise ValueError("version must be a single version, never a range")
        if any(segment in _VERSION_WILDCARD_SEGMENTS for segment in value.split(".")):
            raise ValueError("version must not contain wildcard segments")
        return value

    def endpoint_urls(self) -> frozenset[str]:
        """The raw `remotes[].url` values, templates unresolved.

        This is the dedup key for discovered servers: hosts MUST de-duplicate
        on endpoints, never on the self-asserted name or catalog identifier.
        """
        return frozenset(remote.url for remote in self.remotes or [])


@dataclass(frozen=True, slots=True)
class ResolvedRemote:
    """A `Remote` with every template variable substituted, ready to connect."""

    type: Literal["streamable-http", "sse"]
    url: str
    headers: dict[str, str]


def _substitute(template: str, mapping: Mapping[str, str]) -> tuple[str, set[str]]:
    """Replace `{name}` placeholders from `mapping`, collecting unresolved names."""
    unresolved: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in mapping:
            return mapping[name]
        unresolved.add(name)
        return match.group(0)

    return _TEMPLATE_VARIABLE.sub(replace, template), unresolved


def _resolve_input(name: str, spec: Input, values: Mapping[str, str] | None) -> str | None:
    """The effective value for one input, or None when nothing supplies it.

    A pre-set `value` is not end-user configurable, so it wins. Caller values
    override declared defaults.
    """
    if spec.value is not None:
        return spec.value
    if values is not None and name in values:
        return values[name]
    return spec.default


def _resolve_variables(
    declared: Mapping[str, Input] | None,
    values: Mapping[str, str] | None,
    missing: set[str],
    bad_choices: list[str],
) -> dict[str, str]:
    """Build the substitution mapping for one template scope.

    Caller values apply to undeclared names too. Missing required names and
    values outside a declared `choices` list are collected, never raised here.
    """
    mapping: dict[str, str] = dict(values or {})
    for name, spec in (declared or {}).items():
        resolved = _resolve_input(name, spec, values)
        if resolved is None:
            if spec.is_required:
                missing.add(name)
            continue
        if spec.choices is not None and resolved not in spec.choices:
            bad_choices.append(f"{name}={resolved!r} (choices: {spec.choices})")
            continue
        mapping[name] = resolved
    return mapping


def resolve_remote(remote: Remote, values: Mapping[str, str] | None = None) -> ResolvedRemote:
    """Substitute every `{curly_brace}` variable in `remote`, purely in memory.

    Declared `default`s and pre-set `value`s apply automatically. Caller
    `values` override defaults and also supply header values by header name.
    No prompting, no persistence and no `isSecret` handling happens here.
    Those belong to the host application.

    Raises:
        ValueError: Naming every missing `isRequired` variable, any value
            outside a declared `choices` list, any placeholder left
            unresolved, or a resolved URL that is not http(s).
    """
    missing: set[str] = set()
    bad_choices: list[str] = []
    unresolved: set[str] = set()

    url_mapping = _resolve_variables(remote.variables, values, missing, bad_choices)
    url, url_unresolved = _substitute(remote.url, url_mapping)
    unresolved |= url_unresolved

    headers: dict[str, str] = {}
    for header in remote.headers or []:
        template = _resolve_input(header.name, header, values)
        if template is None:
            if header.is_required:
                missing.add(header.name)
            continue
        if header.choices is not None and template not in header.choices:
            bad_choices.append(f"{header.name}={template!r} (choices: {header.choices})")
            continue
        header_mapping = _resolve_variables(header.variables, values, missing, bad_choices)
        resolved_value, value_unresolved = _substitute(template, header_mapping)
        unresolved |= value_unresolved
        headers[header.name] = resolved_value

    if missing:
        raise ValueError(f"missing required variables: {', '.join(sorted(missing))}")
    if bad_choices:
        raise ValueError(f"values outside declared choices: {'; '.join(bad_choices)}")
    if unresolved:
        raise ValueError(f"unresolved template variables: {', '.join(sorted(unresolved))}")
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"resolved remote URL must be http(s), got {url!r}")
    return ResolvedRemote(type=remote.type, url=url, headers=headers)
