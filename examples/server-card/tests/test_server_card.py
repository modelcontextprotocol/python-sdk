"""Tests for the example Server Card implementation."""

from __future__ import annotations

import pytest

from mcp_server_card import (
    SERVER_CARD_SCHEMA_URL,
    SERVER_SCHEMA_URL,
    ServerCardValidationError,
    build_server_card,
    card_to_dict,
    parse_server,
    parse_server_card,
    streamable_http_remote,
    validate_against_schema,
)
from mcp_server_card.types import KeyValueInput, Repository

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
}

WITH_PACKAGE = {
    "$schema": SERVER_SCHEMA_URL,
    "name": "example-org/with-package",
    "version": "0.4.2",
    "description": "Server document with a locally-runnable npm package.",
    "repository": {"url": "https://github.com/example-org/with-package", "source": "github"},
    "packages": [
        {
            "registryType": "npm",
            "identifier": "@example-org/with-package",
            "version": "0.4.2",
            "runtimeHint": "npx",
            "transport": {"type": "stdio"},
            "environmentVariables": [
                {"name": "EXAMPLE_API_KEY", "description": "Example API key.", "isRequired": True, "isSecret": True}
            ],
        }
    ],
}


@pytest.mark.parametrize("doc", [MINIMAL, TEMPLATED_REMOTE])
def test_valid_cards_parse(doc: dict) -> None:
    card = parse_server_card(doc)
    assert card.name == doc["name"]
    # Round-trips back to exactly the input (modulo key ordering).
    assert card_to_dict(card) == doc


def test_server_with_package_parses_and_discriminates_transport() -> None:
    server = parse_server(WITH_PACKAGE)
    assert server.packages is not None
    transport = server.packages[0].transport
    assert transport.type == "stdio"
    assert card_to_dict(server) == WITH_PACKAGE


def test_build_server_card_round_trips_through_schema() -> None:
    card = build_server_card(
        name="io.modelcontextprotocol.examples/dice",
        version="1.0.0",
        description="Rolls dice.",
        title="Dice",
        repository=Repository(url="https://github.com/example/dice", source="github"),
        remotes=[streamable_http_remote("https://dice.example.com/mcp", supported_protocol_versions=["2025-11-25"])],
    )
    assert validate_against_schema(card_to_dict(card)) == []
    assert parse_server_card(card_to_dict(card)) == card


def test_header_value_with_variables_serializes_camelcase() -> None:
    header = KeyValueInput(name="Authorization", is_required=True, value="Bearer {t}")
    dumped = header.model_dump(by_alias=True, exclude_none=True)
    assert dumped == {"name": "Authorization", "isRequired": True, "value": "Bearer {t}"}


@pytest.mark.parametrize(
    "doc, needle",
    [
        ({**MINIMAL, "name": "no-slash"}, "name"),
        ({k: v for k, v in MINIMAL.items() if k != "$schema"}, "$schema"),
        ({k: v for k, v in MINIMAL.items() if k != "name"}, "name"),
        ({**MINIMAL, "$schema": "https://static.modelcontextprotocol.io/schemas/2025-11-25/server-card.schema.json"},
         "$schema"),
        ({**MINIMAL, "version": "^1.2.3"}, "version"),  # semantic guard (not in JSON Schema)
    ],
)
def test_invalid_cards_rejected(doc: dict, needle: str) -> None:
    with pytest.raises(ServerCardValidationError) as excinfo:
        parse_server_card(doc)
    assert any(needle in error for error in excinfo.value.errors)
