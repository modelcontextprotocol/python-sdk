"""Tests for Server Card models."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from mcp.shared.experimental.server_card import (
    SERVER_CARD_SCHEMA_URL,
    SERVER_SCHEMA_URL,
    KeyValueInput,
    Server,
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

WITH_PACKAGE = {
    "$schema": SERVER_SCHEMA_URL,
    "name": "example-org/with-package",
    "version": "0.4.2",
    "description": "Server document with a locally-runnable npm package.",
    "repository": {"url": "https://github.com/example-org/with-package", "source": "github"},
    "icons": [{"src": "https://example.com/icon.png", "mimeType": "image/png", "sizes": ["48x48"]}],
    "packages": [
        {
            "registryType": "npm",
            "identifier": "@example-org/with-package",
            "version": "0.4.2",
            "runtimeHint": "npx",
            "transport": {"type": "stdio"},
            "packageArguments": [{"type": "positional", "valueHint": "config", "value": "config.json"}],
            "runtimeArguments": [{"type": "named", "name": "--prefix", "value": "/opt"}],
            "environmentVariables": [
                {"name": "EXAMPLE_API_KEY", "description": "Example API key.", "isRequired": True, "isSecret": True}
            ],
            "fileSha256": "a" * 64,
        }
    ],
}


@pytest.mark.parametrize("doc", [MINIMAL, TEMPLATED_REMOTE])
def test_server_card_round_trips(doc: dict[str, Any]) -> None:
    card = ServerCard.model_validate(doc)
    assert card.model_dump(mode="json", by_alias=True, exclude_none=True) == doc


def test_server_with_packages_round_trips_and_discriminates() -> None:
    server = Server.model_validate(WITH_PACKAGE)
    assert server.packages is not None
    assert server.packages[0].transport.type == "stdio"
    assert server.packages[0].package_arguments is not None
    assert server.packages[0].package_arguments[0].type == "positional"
    assert server.packages[0].runtime_arguments is not None
    assert server.packages[0].runtime_arguments[0].type == "named"
    assert server.model_dump(mode="json", by_alias=True, exclude_none=True) == WITH_PACKAGE


def test_default_schema_urls() -> None:
    assert ServerCard(name="a/b", version="1.0.0", description="d").schema_uri == SERVER_CARD_SCHEMA_URL
    assert Server(name="a/b", version="1.0.0", description="d").schema_uri == SERVER_SCHEMA_URL


def test_fields_settable_by_python_name_and_serialize_camelcase() -> None:
    header = KeyValueInput(name="Authorization", is_required=True, value="Bearer {t}")
    assert header.model_dump(by_alias=True, exclude_none=True) == {
        "name": "Authorization",
        "isRequired": True,
        "value": "Bearer {t}",
    }


@pytest.mark.parametrize("version", ["^1.2.3", "~1.2.3", ">=1.2.3", "1.x", "1.2.X", "1.*", "x", "*"])
def test_version_ranges_rejected(version: str) -> None:
    with pytest.raises(ValidationError, match="exact version"):
        ServerCard(name="a/b", version=version, description="d")


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
        ({**MINIMAL, "description": ""}, "description"),
    ],
)
def test_invalid_cards_rejected(doc: dict[str, Any], field: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        ServerCard.model_validate(doc)
    assert field in str(excinfo.value)
