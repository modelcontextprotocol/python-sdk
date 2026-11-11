"""Tests for Server Card models."""

from typing import Any

import pytest
from pydantic import ValidationError

from mcp.shared.experimental.server_card import (
    SERVER_CARD_SCHEMA_URL,
    KeyValueInput,
    ServerCard,
)

MINIMAL = {
    "$schema": SERVER_CARD_SCHEMA_URL,
    "name": "example-org/minimal",
    "version": "1.0.0",
    "description": "Smallest valid Server Card.",
}

TEMPLATED_REMOTE = {
    "$schema": SERVER_CARD_SCHEMA_URL,
    "name": "example-org/with-remote",
    "version": "2.1.0",
    "description": "Server Card with a templated remote endpoint and headers.",
    "title": "Example Remote Server",
    "websiteUrl": "https://example.com",
    "remotes": [
        {
            "type": "streamable-http",
            "url": "https://{tenant}.example.com/mcp",
            "headers": [
                {
                    "name": "Authorization",
                    "description": "Bearer token for the remote endpoint.",
                    "isRequired": True,
                    "isSecret": True,
                    "value": "Bearer {token}",
                    "variables": {"token": {"isRequired": True, "isSecret": True}},
                }
            ],
            "variables": {"tenant": {"isRequired": True, "default": "default"}},
            "supportedProtocolVersions": ["2025-06-18", "2025-11-25"],
        }
    ],
    "_meta": {"com.example/internal": {"tier": "gold"}},
}


@pytest.mark.parametrize("doc", [MINIMAL, TEMPLATED_REMOTE])
def test_server_card_round_trips(doc: dict[str, Any]) -> None:
    card = ServerCard.model_validate(doc)
    assert card.model_dump(mode="json", by_alias=True, exclude_none=True) == doc


def test_default_schema_url() -> None:
    assert ServerCard(name="a/b", version="1.0.0", description="d").schema_uri == SERVER_CARD_SCHEMA_URL


def test_fields_settable_by_python_name_and_serialize_camelcase() -> None:
    header = KeyValueInput(name="Authorization", is_required=True, value="Bearer {t}")
    assert header.model_dump(by_alias=True, exclude_none=True) == {
        "name": "Authorization",
        "isRequired": True,
        "value": "Bearer {t}",
    }


@pytest.mark.parametrize(
    "version", ["^1.2.3", "~1.2.3", ">=1.2.3", "1.x", "1.2.X", "1.*", "x", "*", "1.0.0 - 2.0.0", "1.0.0 || 2.0.0"]
)
def test_version_ranges_rejected(version: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        ServerCard(name="a/b", version=version, description="d")
    # Pydantic wraps the SDK validator error, so assert only its stable prefix.
    error = excinfo.value.errors()[0]
    assert "ctx" in error
    assert str(error["ctx"]["error"]).startswith("version must be an exact version")


@pytest.mark.parametrize("version", ["1.0.0", "1.0.0-x", "1.0.0-X.1", "1.0.0-rc.x", "2024-01-05"])
def test_exact_versions_accepted(version: str) -> None:
    """Semver prereleases like 1.0.0-x are exact versions, not wildcards."""
    assert ServerCard(name="a/b", version=version, description="d").version == version


@pytest.mark.parametrize(
    "doc, field",
    [
        ({**MINIMAL, "name": "no-slash"}, "name"),
        (
            {**MINIMAL, "$schema": "https://static.modelcontextprotocol.io/schemas/2025-11-25/server-card.schema.json"},
            "$schema",
        ),
        (
            {**MINIMAL, "$schema": "https://static.modelcontextprotocol.io/schemas/v1/server.schema.json"},
            "$schema",
        ),
        ({**MINIMAL, "description": ""}, "description"),
    ],
)
def test_invalid_cards_rejected(doc: dict[str, Any], field: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        ServerCard.model_validate(doc)
    assert field in str(excinfo.value)
