"""Pydantic models for AI Catalogs.

WARNING: These APIs are experimental and may change without notice.

An AI Catalog is a typed, nestable JSON container for discovering
heterogeneous AI artifacts (MCP servers, A2A agents, skills, nested
catalogs, ...). Each entry declares its artifact type via a media type and
either references the artifact by URL or embeds it inline. Hosts advertise a
catalog at ``/.well-known/ai-catalog.json`` so clients can discover artifacts
— for MCP, the Server Cards in ``mcp.shared.experimental.server_card`` —
without prior configuration.

The models mirror the normative CDDL schema of the AI Catalog specification,
including the optional Trust Manifest extension. The MCP Catalog defined by
the MCP discovery extension is a structural subset of an AI Catalog, so these
models ingest both document flavours.

See https://github.com/Agent-Card/ai-catalog and
https://github.com/modelcontextprotocol/experimental-ext-server-card/blob/main/docs/discovery.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from mcp_types._types import MCPModel
from pydantic import Field, model_validator

#: Media type identifying an AI Catalog document.
AI_CATALOG_MEDIA_TYPE = "application/ai-catalog+json"
#: Media type identifying an MCP Server Card artifact in a catalog entry,
#: per the MCP discovery extension.
MCP_SERVER_CARD_MEDIA_TYPE = "application/mcp-server-card+json"
#: Well-known path an AI Catalog is published at, relative to the host root.
AI_CATALOG_WELL_KNOWN_PATH = "/.well-known/ai-catalog.json"
#: Well-known path of the MCP-scoped catalog defined by the MCP discovery
#: extension. A structural subset of an AI Catalog, so it parses with these models.
MCP_CATALOG_WELL_KNOWN_PATH = "/.well-known/mcp/catalog.json"
#: URN prefix for AI Catalog entry identifiers. MCP server entries use
#: ``urn:air:{publisher}:{name}`` where ``publisher`` is the forward-DNS form of
#: the card name's namespace (``com.example/weather`` -> ``urn:air:example.com:weather``).
AI_CATALOG_URN_PREFIX = "urn:air:"


class TrustSchema(MCPModel):
    """The trust framework applied to an artifact."""

    identifier: str
    """Identifier of the trust schema."""

    version: str
    """Version of the trust schema."""

    governance_uri: str | None = None
    """URI of the governance policy document."""

    verification_methods: list[str] | None = None
    """Supported verification methods (e.g. ``"did"``, ``"x509"``, ``"dns-01"``)."""


class Attestation(MCPModel):
    """A verifiable proof of a claim about an artifact."""

    type: str
    """Attestation type (e.g. ``"publisher-identity"``, ``"SOC2-Type2"``)."""

    uri: str
    """Location of the attestation document (HTTPS URL or Data URI)."""

    media_type: str
    """Format of the attestation document (e.g. ``"application/jwt"``)."""

    digest: str | None = None
    """Cryptographic hash for integrity verification (``algorithm:hex-value``)."""

    size: Annotated[int, Field(ge=0)] | None = None
    """Size of the attestation document in bytes."""

    description: str | None = None
    """Human-readable label."""


class ProvenanceLink(MCPModel):
    """Lineage information for an artifact."""

    relation: str
    """The relationship (e.g. ``"publishedFrom"``, ``"derivedFrom"``)."""

    source_id: str
    """Identifier of the source artifact or data."""

    source_digest: str | None = None
    """Digest of the source."""

    registry_uri: str | None = None
    """URI of the registry holding the source."""

    statement_uri: str | None = None
    """URI of a provenance statement document."""

    signature_ref: str | None = None
    """Reference to the key used to sign the provenance statement."""


class TrustManifest(MCPModel):
    """Verifiable identity, attestation and provenance metadata for an artifact.

    An optional companion to catalog entries and hosts; it sits alongside the
    artifact without wrapping or modifying its native format.
    """

    identity: str
    """Globally unique URI serving as the subject identifier (DID, SPIFFE ID, URL)."""

    identity_type: str | None = None
    """Type hint for the identity URI (e.g. ``"did"``, ``"spiffe"``, ``"dns"``)."""

    trust_schema: TrustSchema | None = None
    """The trust framework applied to the artifact."""

    attestations: list[Attestation] | None = None
    """Verifiable claims (publisher identity, compliance certifications, ...)."""

    provenance: list[ProvenanceLink] | None = None
    """Lineage of the artifact."""

    privacy_policy_url: str | None = None
    """URL to the privacy policy governing the artifact."""

    terms_of_service_url: str | None = None
    """URL to the terms of service."""

    signature: str | None = None
    """Detached JWS signature computed over the Trust Manifest content."""

    metadata: dict[str, Any] | None = None
    """Open map for custom or non-standard trust metadata."""


class Publisher(MCPModel):
    """The entity responsible for publishing an artifact."""

    identifier: str
    """Verifiable identifier for the publisher organization."""

    display_name: str
    """Human-readable name of the publisher."""

    identity_type: str | None = None
    """Type hint for the publisher identifier (e.g. ``"did"``, ``"dns"``)."""


class HostInfo(MCPModel):
    """The operator of a catalog."""

    display_name: str
    """Human-readable name of the host (e.g. the organization name)."""

    identifier: str | None = None
    """Verifiable identifier for the host (e.g. a DID or domain name)."""

    documentation_url: str | None = None
    """URL to the host's documentation."""

    logo_url: str | None = None
    """URL to the host's logo."""

    trust_manifest: TrustManifest | None = None
    """Trust metadata for the host itself."""


class CatalogEntry(MCPModel):
    """A single AI artifact in a catalog.

    Exactly one of ``url`` (artifact by reference) or ``data`` (artifact
    inline) must be provided.
    """

    identifier: str
    """Identifier for the artifact; SHOULD be a URN or URI.

    MCP server entries use ``urn:air:{publisher}:{name}``, where ``publisher`` is
    the forward-DNS form of the referenced Server Card's namespace and ``name``
    is its name suffix.
    """

    display_name: str
    """Human-readable name for the artifact."""

    media_type: str
    """Media type identifying the artifact type (e.g. ``"application/mcp-server-card+json"``)."""

    url: str | None = None
    """URL where the full artifact document can be retrieved."""

    data: Any = None
    """The complete artifact document inline; its structure is determined by ``media_type``."""

    version: str | None = None
    """Version of the artifact. Semantic versioning is recommended."""

    description: str | None = None
    """Short description of the artifact."""

    tags: list[str] | None = None
    """Keywords for filtering and discovery."""

    publisher: Publisher | None = None
    """The entity that publishes this artifact."""

    trust_manifest: TrustManifest | None = None
    """Trust metadata for this artifact; its ``identity`` must equal ``identifier``."""

    updated_at: datetime | None = None
    """When this entry was last modified."""

    metadata: dict[str, Any] | None = None
    """Open map for custom or non-standard metadata."""

    @model_validator(mode="after")
    def _check_content_and_trust(self) -> CatalogEntry:
        if (self.url is None) == (self.data is None):
            raise ValueError("a catalog entry must provide exactly one of 'url' or 'data'")
        # The spec requires consumers to reject a Trust Manifest whose identity
        # does not match the containing entry's identifier.
        if self.trust_manifest is not None and self.trust_manifest.identity != self.identifier:
            raise ValueError(
                f"trust manifest identity {self.trust_manifest.identity!r} "
                f"does not match entry identifier {self.identifier!r}"
            )
        return self


class AICatalog(MCPModel):
    """A catalog of AI artifacts, served as ``application/ai-catalog+json``.

    A minimal catalog is just ``entries`` — names, media types and URLs. A
    catalog may be served from any URL; hosts that want automated discovery
    publish one at ``/.well-known/ai-catalog.json``.
    """

    spec_version: str = "1.0"
    """The AI Catalog specification version, in ``"Major.Minor"`` format.

    Required by the specification; defaulted here for documents that omit it.
    """

    entries: list[CatalogEntry]
    """The cataloged artifacts. May be empty."""

    host: HostInfo | None = None
    """The operator of this catalog."""

    metadata: dict[str, Any] | None = None
    """Open map for custom or non-standard metadata."""
