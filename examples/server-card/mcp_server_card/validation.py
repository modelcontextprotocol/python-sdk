"""Validation for MCP Server Card documents.

Two layers, both surfaced through :func:`parse_server_card` / :func:`parse_server`:

1. **JSON Schema** — the document is checked against the generated
   ``schema.json`` (the same artifact CI in ``experimental-ext-server-card``
   validates examples against). This is the authoritative structural check.
2. **Pydantic** — the validated dict is parsed into the typed models, applying
   the field constraints and the extra semantic guards (e.g. version ranges)
   that JSON Schema can't express.

Clients consuming an untrusted card should always go through these functions
rather than constructing the models directly.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JSONSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

from .types import Server, ServerCard

__all__ = [
    "ServerCardValidationError",
    "load_bundled_schema",
    "validate_against_schema",
    "parse_server_card",
    "parse_server",
]

# Version strings that look like ranges/wildcards. The spec allows non-semantic
# versions but rejects ranges; JSON Schema only bounds length, so we guard here.
_VERSION_RANGE_RE = re.compile(r"[\^~]|[<>]=?|\.\*|\bx\b", re.IGNORECASE)


class ServerCardValidationError(Exception):
    """Raised when a document fails Server Card validation.

    ``errors`` holds one human-readable string per problem found, so a client
    can show the user everything that is wrong at once.
    """

    def __init__(self, message: str, errors: list[str]):
        super().__init__(message + "\n  - " + "\n  - ".join(errors))
        self.errors = errors


@lru_cache(maxsize=1)
def load_bundled_schema() -> dict[str, Any]:
    """Load the JSON Schema bundled alongside this package."""
    text = resources.files(__package__).joinpath("schema.json").read_text(encoding="utf-8")
    return json.loads(text)


@lru_cache(maxsize=4)
def _validator_for(definition: str) -> Draft202012Validator:
    """Build a validator scoped to a single ``$defs`` entry of the bundled schema."""
    schema = load_bundled_schema()
    if definition not in schema.get("$defs", {}):
        raise KeyError(f"No '{definition}' definition in bundled schema")
    # The bundled schema has no root type (it is generated with `*`), so point a
    # tiny root schema at the wanted definition while keeping its $defs in scope.
    scoped = {"$schema": schema.get("$schema"), "$ref": f"#/$defs/{definition}", "$defs": schema["$defs"]}
    return Draft202012Validator(scoped)


def _format_error(error: JSONSchemaValidationError) -> str:
    location = "/".join(str(p) for p in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


def validate_against_schema(data: dict[str, Any], definition: str = "ServerCard") -> list[str]:
    """Validate ``data`` against a ``$defs`` entry; return error strings (empty == valid)."""
    validator = _validator_for(definition)
    return [_format_error(e) for e in sorted(validator.iter_errors(data), key=str)]


def _semantic_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    version = data.get("version")
    if isinstance(version, str) and _VERSION_RANGE_RE.search(version):
        errors.append(f"version: '{version}' looks like a range/wildcard; an exact version is required")
    return errors


def _parse(data: dict[str, Any], model: type[ServerCard], definition: str) -> ServerCard:
    if not isinstance(data, dict):
        raise ServerCardValidationError("Document is not a JSON object", ["<root>: expected an object"])

    errors = validate_against_schema(data, definition)
    errors += _semantic_errors(data)
    if errors:
        raise ServerCardValidationError(f"Invalid {definition} document", errors)

    try:
        return model.model_validate(data)
    except PydanticValidationError as exc:  # pragma: no cover - schema should catch first
        raise ServerCardValidationError(
            f"Invalid {definition} document",
            [f"{'/'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()],
        ) from exc


def parse_server_card(data: dict[str, Any]) -> ServerCard:
    """Validate and parse a Server Card document (the ``.well-known`` shape)."""
    return _parse(data, ServerCard, "ServerCard")


def parse_server(data: dict[str, Any]) -> Server:
    """Validate and parse a registry-shaped Server document (adds ``packages``)."""
    return _parse(data, Server, "Server")  # type: ignore[return-value]
