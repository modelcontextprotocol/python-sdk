"""`mcp.shared.experimental.ai_catalog`: catalog models and the url-xor-data rule."""

import json

import pytest
from pydantic import ValidationError

from mcp.shared.experimental.ai_catalog import AICatalog, CatalogEntry


def test_entry_with_url_only_is_valid() -> None:
    """Spec-mandated: an entry may reference its artifact by URL."""
    entry = CatalogEntry(
        identifier="urn:air:example.com:mcp:weather",
        type="application/mcp-server-card+json",
        url="https://example.com/mcp/server-card",
    )
    assert entry.data is None


def test_entry_with_inline_data_only_is_valid() -> None:
    """Spec-mandated: an entry may inline its artifact as `data` instead of a URL."""
    entry = CatalogEntry(
        identifier="urn:air:example.com:mcp:weather",
        type="application/mcp-server-card+json",
        data={"name": "com.example/weather"},
    )
    assert entry.url is None


def test_entry_with_both_url_and_data_is_rejected() -> None:
    """Spec-mandated: `url` and `data` are mutually exclusive."""
    with pytest.raises(ValidationError):
        CatalogEntry(
            identifier="urn:air:x:mcp:y", type="application/mcp-server-card+json", url="https://example.com/c", data={}
        )


def test_entry_with_neither_url_nor_data_is_rejected() -> None:
    """Spec-mandated: an entry must carry its artifact one way or the other."""
    with pytest.raises(ValidationError):
        CatalogEntry(identifier="urn:air:x:mcp:y", type="application/mcp-server-card+json")


def test_catalog_with_empty_entries_is_valid() -> None:
    """Spec-mandated: `entries` is required but may be empty."""
    assert AICatalog(spec_version="1.0", entries=[]).entries == []


def test_trust_and_publisher_shapes_pass_through_verbatim() -> None:
    """SDK-defined: `publisher`, `trustManifest` and `host` are untyped passthrough for
    the host's consent UI. The AI Catalog working group owns their shapes."""
    document = {
        "specVersion": "1.0",
        "host": {"displayName": "Example Inc.", "identifier": "example.com"},
        "entries": [
            {
                "identifier": "urn:air:example.com:mcp:weather",
                "type": "application/mcp-server-card+json",
                "url": "https://example.com/mcp/server-card",
                "displayName": "Weather",
                "updatedAt": "2026-07-01T00:00:00Z",
                "publisher": {"identifier": "example.com", "displayName": "Example Inc."},
                "trustManifest": {"identity": "did:web:example.com"},
            }
        ],
    }
    catalog = AICatalog.model_validate(document)
    assert catalog.entries[0].trust_manifest == {"identity": "did:web:example.com"}
    assert json.loads(catalog.model_dump_json(by_alias=True, exclude_none=True)) == document
