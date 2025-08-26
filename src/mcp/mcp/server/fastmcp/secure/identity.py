"""
Identity management for secure MCP operations.

Handles both tool identity (server-side) and client identity verification.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa, padding
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes, PublicKeyTypes
from cryptography.x509.oid import NameOID

from .annotations import AuthMethod


@dataclass
class ToolIdentity:
    """
    Represents the cryptographic identity of a tool/server.
    
    This is used for:
    - Tool attestation (proving the tool is legitimate)
    - Response signing (ensuring response integrity)
    - Mutual authentication (bidirectional auth with client)
    """
    
    tool_id: str
    name: str
    version: str
    certificate: x509.Certificate
    private_key: PrivateKeyTypes
    trusted_issuers: list[x509.Certificate]
    
    # Optional attestation for secure enclaves
    attestation_report: Optional[dict] = None
    attestation_type: Optional[str] = None  # "software", "sgx", "sev", "trustzone"
    
    # Tool capabilities and metadata
    capabilities: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)
    
    @property
    def fingerprint(self) -> str:
        """Get SHA256 fingerprint of the tool's certificate."""
        cert_der = self.certificate.public_bytes(serialization.Encoding.DER)
        return hashlib.sha256(cert_der).hexdigest()
    
    @property
    def public_key(self) -> PublicKeyTypes:
        """Get the public key from the certificate."""
        return self.certificate.public_key()
    
    def sign_data(self, data: bytes) -> bytes:
        """
        Sign data with the tool's private key.
        
        Args:
            data: Data to sign
        
        Returns:
            Digital signature
        """
        if isinstance(self.private_key, rsa.RSAPrivateKey):
            return self.private_key.sign(
                data,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
        elif isinstance(self.private_key, ec.EllipticCurvePrivateKey):
            return self.private_key.sign(data, ec.ECDSA(hashes.SHA256()))
        else:
            raise ValueError(f"Unsupported key type: {type(self.private_key)}")
    
    def verify_signature(self, data: bytes, signature: bytes, public_key: PublicKeyTypes) -> bool:
        """
        Verify a signature using a public key.
        
        Args:
            data: Original data
            signature: Signature to verify
            public_key: Public key to verify with
        
        Returns:
            True if signature is valid
        """
        try:
            if isinstance(public_key, rsa.RSAPublicKey):
                public_key.verify(
                    signature,
                    data,
                    padding.PSS(
                        mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH
                    ),
                    hashes.SHA256()
                )
            elif isinstance(public_key, ec.EllipticCurvePublicKey):
                public_key.verify(signature, data, ec.ECDSA(hashes.SHA256()))
            else:
                return False
            return True
        except Exception:
            return False
    
    def to_attestation(self) -> dict[str, Any]:
        """
        Generate attestation data for the tool.
        
        Returns:
            Dictionary containing tool attestation information
        """
        import base64
        
        attestation = {
            "tool_id": self.tool_id,
            "name": self.name,
            "version": self.version,
            "fingerprint": self.fingerprint,
            "certificate": base64.b64encode(
                self.certificate.public_bytes(serialization.Encoding.PEM)
            ).decode(),
            "capabilities": list(self.capabilities),
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Add hardware attestation if available
        if self.attestation_report:
            attestation["attestation"] = {
                "type": self.attestation_type,
                "report": self.attestation_report,
            }
        
        # Sign the attestation
        attestation_bytes = json.dumps(attestation, sort_keys=True).encode()
        signature = self.sign_data(attestation_bytes)
        attestation["signature"] = base64.b64encode(signature).decode()
        
        return attestation
    
    def verify_client_signature(self, data: bytes, signature: bytes, client_cert: x509.Certificate) -> bool:
        """
        Verify a signature from a client certificate.
        
        Args:
            data: Data that was signed
            signature: Client's signature
            client_cert: Client's certificate
        
        Returns:
            True if signature is valid
        """
        client_public_key = client_cert.public_key()
        return self.verify_signature(data, signature, client_public_key)


@dataclass
class ClientIdentity:
    """
    Represents an authenticated client identity.
    
    This is created after successful authentication and contains
    the client's permissions and metadata.
    """
    
    client_id: str
    authentication_method: AuthMethod
    credentials: Any  # JWT token, certificate, attestation, etc.
    permissions: set[str]
    
    # Optional fields
    session_id: Optional[str] = None
    organization: Optional[str] = None
    email: Optional[str] = None
    
    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    authenticated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    
    # Certificate-based auth specifics
    certificate: Optional[x509.Certificate] = None
    certificate_fingerprint: Optional[str] = None
    
    # Rate limiting and quotas
    rate_limit: Optional[int] = None
    quota_remaining: Optional[int] = None
    
    def has_permission(self, permission: str) -> bool:
        """
        Check if client has a specific permission.
        
        Args:
            permission: Permission to check (e.g., "tool.execute", "resource.read")
        
        Returns:
            True if client has the permission
        """
        # Check exact permission
        if permission in self.permissions:
            return True
        
        # Check wildcard permissions
        if "*" in self.permissions:
            return True
        
        # Check hierarchical permissions (e.g., "tool.*" matches "tool.execute")
        parts = permission.split(".")
        for i in range(len(parts)):
            wildcard_perm = ".".join(parts[:i+1]) + ".*"
            if wildcard_perm in self.permissions:
                return True
        
        return False
    
    def is_expired(self) -> bool:
        """Check if the client identity has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "client_id": self.client_id,
            "authentication_method": self.authentication_method.value,
            "permissions": list(self.permissions),
            "organization": self.organization,
            "email": self.email,
            "authenticated_at": self.authenticated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "certificate_fingerprint": self.certificate_fingerprint,
            "metadata": self.metadata,
        }


def create_tool_identity(
    tool_name: str,
    tool_version: str,
    organization: str = "MCP-Secure",
    country: str = "US",
    validity_days: int = 365,
    key_type: str = "EC"  # "EC" or "RSA"
) -> ToolIdentity:
    """
    Create a tool identity with a self-signed certificate.
    
    In production, you would use a proper CA-signed certificate.
    
    Args:
        tool_name: Name of the tool
        tool_version: Version of the tool
        organization: Organization name
        country: Country code
        validity_days: Certificate validity period
        key_type: Key type ("EC" for elliptic curve, "RSA" for RSA)
    
    Returns:
        ToolIdentity with generated certificate and key
    """
    # Generate key pair
    if key_type == "RSA":
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    else:  # EC
        private_key = ec.generate_private_key(ec.SECP256R1())
    
    # Create certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, country),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "MCP-Tools"),
        x509.NameAttribute(NameOID.COMMON_NAME, f"{tool_name}-v{tool_version}"),
    ])
    
    # Build certificate
    builder = x509.CertificateBuilder()
    builder = builder.subject_name(subject)
    builder = builder.issuer_name(issuer)
    builder = builder.public_key(private_key.public_key())
    builder = builder.serial_number(x509.random_serial_number())
    builder = builder.not_valid_before(datetime.utcnow())
    builder = builder.not_valid_after(datetime.utcnow() + timedelta(days=validity_days))
    
    # Add extensions
    builder = builder.add_extension(
        x509.SubjectAlternativeName([
            x509.DNSName(f"{tool_name}.local"),
            x509.DNSName("localhost"),
        ]),
        critical=False,
    )
    
    builder = builder.add_extension(
        x509.KeyUsage(
            digital_signature=True,
            key_encipherment=True,
            content_commitment=True,
            data_encipherment=False,
            key_agreement=True,
            key_cert_sign=False,
            crl_sign=False,
            encipher_only=False,
            decipher_only=False,
        ),
        critical=True,
    )
    
    builder = builder.add_extension(
        x509.ExtendedKeyUsage([
            x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
            x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
        ]),
        critical=True,
    )
    
    # Self-sign the certificate
    certificate = builder.sign(private_key, hashes.SHA256())
    
    return ToolIdentity(
        tool_id=f"{tool_name}-{tool_version}",
        name=tool_name,
        version=tool_version,
        certificate=certificate,
        private_key=private_key,
        trusted_issuers=[certificate],  # Self-signed
        capabilities={
            "authentication.mutual",
            "encryption.aes256",
            "signing.sha256",
        },
        metadata={
            "created_at": datetime.utcnow().isoformat(),
            "key_type": key_type,
            "organization": organization,
        }
    )


def verify_tool_certificate(
    certificate: x509.Certificate,
    trusted_cas: list[x509.Certificate],
    check_revocation: bool = True
) -> tuple[bool, Optional[str]]:
    """
    Verify a tool's certificate against trusted CAs.
    
    Args:
        certificate: Certificate to verify
        trusted_cas: List of trusted CA certificates
        check_revocation: Whether to check certificate revocation
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check certificate validity period
    now = datetime.utcnow()
    if now < certificate.not_valid_before:
        return False, "Certificate not yet valid"
    if now > certificate.not_valid_after:
        return False, "Certificate has expired"
    
    # Verify certificate chain
    for ca in trusted_cas:
        try:
            ca.public_key().verify(
                certificate.signature,
                certificate.tbs_certificate_bytes,
                certificate.signature_algorithm_oid._name
            )
            
            # If we reach here, signature is valid
            if check_revocation:
                # In production, check CRL or OCSP
                pass
            
            return True, None
        except Exception:
            continue
    
    return False, "Certificate not signed by trusted CA"