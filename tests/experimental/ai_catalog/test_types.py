"""Tests for AI Catalog models."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from mcp.shared.experimental.ai_catalog import (
    AICatalog,
    CatalogEntry,
)

MINIMAL_ENTRY = {
    "identifier": "urn:air:example.com:weather",
    "displayName": "Weather Service",
    "mediaType": "application/mcp-server-card+json",
    "url": "https://example.com/server-card.json",
}

# Trimmed from the AI Catalog specification's multi-artifact example.
FULL_CATALOG = {
    "specVersion": "1.0",
    "host": {
        "displayName": "Acme Enterprise AI",
        "identifier": "did:web:acme-corp.com",
        "documentationUrl": "https://docs.acme-corp.com/ai",
    },
    "entries": [
        {
            "identifier": "urn:acme:agent:finance",
            "displayName": "Acme Finance Agent",
            "version": "2.1.0",
            "mediaType": "application/a2a-agent-card+json",
            "url": "https://api.acme-corp.com/agents/finance/v2.1.json",
            "updatedAt": "2026-03-15T10:00:00Z",
            "tags": ["finance", "agent"],
            "publisher": {
                "identifier": "did:web:acme-corp.com",
                "displayName": "Acme Financial Corp",
                "identityType": "did",
            },
            "trustManifest": {
                "identity": "urn:acme:agent:finance",
                "identityType": "did",
                "trustSchema": {
                    "identifier": "urn:trust:acme-enterprise-v1",
                    "version": "1.0",
                    "governanceUri": "https://acme-corp.com/trust/governance.pdf",
                    "verificationMethods": ["did", "x509"],
                },
                "attestations": [
                    {
                        "type": "SOC2-Type2",
                        "uri": "https://trust.acme-corp.com/reports/soc2.pdf",
                        "mediaType": "application/pdf",
                        "digest": "sha256:" + "a" * 64,
                        "size": 123456,
                        "description": "Annual SOC 2 report",
                    }
                ],
                "provenance": [
                    {
                        "relation": "publishedFrom",
                        "sourceId": "https://github.com/acme-corp/finance-agent",
                        "sourceDigest": "sha256:" + "b" * 64,
                        "registryUri": "oci://registry.acme-corp.com/agents/finance",
                        "statementUri": "https://trust.acme-corp.com/provenance/finance-agent.json",
                        "signatureRef": "did:web:acme-corp.com#key-1",
                    }
                ],
                "privacyPolicyUrl": "https://acme-corp.com/legal/privacy",
                "termsOfServiceUrl": "https://acme-corp.com/legal/terms",
                "signature": "eyJhbGciOiJFUzI1NiJ9..detached-jws-signature",
                "metadata": {"com.acme.reviewCycle": "annual"},
            },
            "metadata": {"com.acme.deploymentRegion": "eu-west-1"},
        },
        {
            "identifier": "urn:air:acme.com:weather",
            "displayName": "Weather Service",
            "mediaType": "application/mcp-server-card+json",
            "data": {"name": "com.acme/weather", "version": "1.0.0", "description": "Weather lookups."},
        },
    ],
    "metadata": {"com.acme.catalogOwner": "platform-team"},
}

# The MCP Catalog from the MCP discovery extension is a structural subset of
# an AI Catalog and must parse with the same models.
MCP_CATALOG = {
    "specVersion": "draft",
    "entries": [
        {
            "identifier": "urn:air:example.com:weather",
            "displayName": "Weather Service",
            "mediaType": "application/mcp-server-card+json",
            "url": "https://example.com/.well-known/mcp-server-card",
        }
    ],
}


@pytest.mark.parametrize("doc", [FULL_CATALOG, MCP_CATALOG])
def test_catalog_round_trips(doc: dict[str, Any]) -> None:
    """A catalog document survives validate -> dump unchanged."""
    catalog = AICatalog.model_validate(doc)
    assert catalog.model_dump(mode="json", by_alias=True, exclude_none=True) == doc


def test_spec_version_defaults_when_omitted() -> None:
    """Ingestion is lenient: a catalog without specVersion gets the current default."""
    catalog = AICatalog.model_validate({"entries": []})
    assert catalog.spec_version == "1.0"


def test_entry_requires_url_or_data() -> None:
    doc = {k: v for k, v in MINIMAL_ENTRY.items() if k != "url"}
    with pytest.raises(ValidationError) as excinfo:
        CatalogEntry.model_validate(doc)
    assert "exactly one of 'url' or 'data'" in str(excinfo.value)


def test_entry_rejects_url_and_data_together() -> None:
    with pytest.raises(ValidationError) as excinfo:
        CatalogEntry.model_validate({**MINIMAL_ENTRY, "data": {"name": "com.example/weather"}})
    assert "exactly one of 'url' or 'data'" in str(excinfo.value)


def test_entry_rejects_mismatched_trust_manifest_identity() -> None:
    """The spec requires rejecting trust manifests bound to a different identifier."""
    with pytest.raises(ValidationError) as excinfo:
        CatalogEntry.model_validate({**MINIMAL_ENTRY, "trustManifest": {"identity": "urn:air:other.example:name"}})
    assert "does not match entry identifier" in str(excinfo.value)


def test_entry_accepts_matching_trust_manifest_identity() -> None:
    entry = CatalogEntry.model_validate({**MINIMAL_ENTRY, "trustManifest": {"identity": MINIMAL_ENTRY["identifier"]}})
    assert entry.trust_manifest is not None
    assert entry.trust_manifest.identity == entry.identifier
