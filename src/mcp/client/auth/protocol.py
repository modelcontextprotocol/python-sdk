"""Auth protocol abstractions.

This module defines the shared interfaces used by the multi-protocol authentication system.
"""

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx

from mcp.shared.auth import AuthCredentials, AuthProtocolMetadata, ProtectedResourceMetadata


# DPoP-related types (implemented as part of the DPoP feature set)
class DPoPStorage(Protocol):
    """Storage interface for DPoP key pairs."""

    async def get_key_pair(self, protocol_id: str) -> Any: ...
    async def set_key_pair(self, protocol_id: str, key_pair: Any) -> None: ...


class DPoPProofGenerator(Protocol):
    """DPoP proof generator interface."""

    def generate_proof(self, method: str, uri: str, credential: str | None = None, nonce: str | None = None) -> str: ...
    def get_public_key_jwk(self) -> dict[str, Any]: ...


class ClientRegistrationResult(Protocol):
    """Client registration result interface."""

    client_id: str
    client_secret: str | None = None


@dataclass
class AuthContext:
    """Generic authentication context."""

    server_url: str
    storage: Any  # TokenStorage protocol type
    protocol_id: str
    protocol_metadata: AuthProtocolMetadata | None = None
    current_credentials: AuthCredentials | None = None
    dpop_storage: DPoPStorage | None = None
    dpop_enabled: bool = False
    # Used by OAuth2Protocol.run_authentication (multi-protocol path; mirrors 401-branch behavior)
    http_client: httpx.AsyncClient | None = None
    resource_metadata_url: str | None = None
    protected_resource_metadata: ProtectedResourceMetadata | None = None
    scope_from_www_auth: str | None = None


class AuthProtocol(Protocol):
    """Base auth protocol interface (all protocols must implement this)."""

    protocol_id: str
    protocol_version: str

    async def authenticate(self, context: AuthContext) -> AuthCredentials:
        """Perform authentication and return credentials.

        Args:
            context: Authentication context.

        Returns:
            Authentication credentials.
        """
        ...

    def prepare_request(self, request: httpx.Request, credentials: AuthCredentials) -> None:
        """Prepare an HTTP request by attaching authentication information.

        Args:
            request: HTTP request object.
            credentials: Authentication credentials.
        """
        ...

    def validate_credentials(self, credentials: AuthCredentials) -> bool:
        """Validate credentials (e.g. ensure they are not expired).

        Args:
            credentials: Credentials to validate.

        Returns:
            True if credentials are valid, False otherwise
        """
        ...

    async def discover_metadata(
        self,
        metadata_url: str | None,
        prm: ProtectedResourceMetadata | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> AuthProtocolMetadata | None:
        """Discover protocol metadata.

        Args:
            metadata_url: Optional metadata URL.
            prm: Optional protected resource metadata.
            http_client: Optional HTTP client for network discovery (e.g. RFC 8414).

        Returns:
            Protocol metadata, or None if discovery fails.
        """
        ...


class ClientRegisterableProtocol(AuthProtocol):
    """Protocol extension for protocols that support client registration."""

    async def register_client(self, context: AuthContext) -> ClientRegistrationResult | None:
        """Register a client.

        Args:
            context: Authentication context.

        Returns:
            Client registration result, or None if registration is not needed or fails.
        """
        ...


@runtime_checkable
class DPoPEnabledProtocol(AuthProtocol, Protocol):
    """Protocol extension for DPoP-capable protocols."""

    def supports_dpop(self) -> bool:
        """Return True if this protocol instance supports DPoP.

        Returns:
            True if protocol supports DPoP, False otherwise
        """
        ...

    def get_dpop_proof_generator(self) -> DPoPProofGenerator | None:
        """Return the DPoP proof generator, if available.

        Returns:
            A DPoP proof generator, or None if not supported or not initialized.
        """
        ...

    async def initialize_dpop(self) -> None:
        """Initialize DPoP (e.g. generate key pairs)."""
        ...
