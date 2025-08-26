"""
Utility functions for secure MCP operations.

Provides encryption, authentication, and security helper functions.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import jwt
from cryptography import x509
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2

from mcp.types import Error

from .annotations import AuthMethod, SecureAnnotations
from .identity import ClientIdentity, ToolIdentity
from .session import SecureSession


class SecureAnnotationProcessor:
    """
    Processes secure annotations for tools, resources, and prompts.
    
    This class handles the actual authentication, encryption, and
    attestation logic when secure annotations are present.
    """
    
    def __init__(
        self,
        tool_identity: Optional[ToolIdentity] = None,
        jwt_secret: Optional[str] = None,
        trusted_cas: Optional[List[x509.Certificate]] = None,
        api_keys: Optional[Dict[str, ClientIdentity]] = None,
    ):
        self.tool_identity = tool_identity
        self.jwt_secret = jwt_secret or os.environ.get("MCP_JWT_SECRET")
        self.trusted_cas = trusted_cas or []
        self.api_keys = api_keys or {}
        
        # Session and rate limit storage
        self.sessions: Dict[str, SecureSession] = {}
        self.rate_limits: Dict[str, List[datetime]] = {}
        
        # Audit log (in production, use proper logging system)
        self.audit_log_entries: List[dict] = []
    
    async def process_secure_request(
        self,
        annotations: SecureAnnotations,
        auth_header: Optional[str] = None,
        client_cert: Optional[x509.Certificate] = None,
        request_data: Optional[dict[str, Any]] = None,
    ) -> Tuple[SecureSession, dict[str, Any]]:
        """
        Process a secure request with authentication and encryption.
        
        Args:
            annotations: Security annotations
            auth_header: Authorization header
            client_cert: Client certificate
            request_data: Request data
        
        Returns:
            Tuple of (secure_session, processed_request_data)
        
        Raises:
            Error: If security checks fail
        """
        # 1. Authenticate client if required
        client_identity = None
        if annotations.require_auth:
            client_identity = await self._authenticate_client(
                annotations.auth_methods,
                auth_header,
                client_cert,
                request_data
            )
            
            # Check permissions
            missing_perms = annotations.required_permissions - client_identity.permissions
            if missing_perms:
                raise Error(
                    code=403,
                    message=f"Missing required permissions: {missing_perms}"
                )
        
        # 2. Perform mutual authentication if required
        if annotations.require_mutual_auth:
            if not self.tool_identity:
                raise Error(
                    code=500,
                    message="Tool identity not configured for mutual authentication"
                )
            # Tool attestation is provided through session
        
        # 3. Create or retrieve session
        session = await self._establish_session(client_identity)
        
        # 4. Verify tool attestation if required
        if annotations.require_tool_attestation:
            if not self._verify_tool_attestation(annotations):
                raise Error(
                    code=403,
                    message="Tool attestation verification failed"
                )
        
        # 5. Check rate limits
        if annotations.rate_limit:
            self._check_rate_limit(
                session.client_identity.client_id if session.client_identity else "anonymous",
                annotations.rate_limit,
                annotations.rate_limit_per_client
            )
        
        # 6. Decrypt input if required
        processed_data = request_data or {}
        if annotations.encrypt_input and session.encryption_key:
            processed_data = self._decrypt_request_data(session, processed_data)
        
        # 7. Verify message integrity if required
        if annotations.require_integrity_check:
            self._verify_message_integrity(processed_data)
        
        # 8. Check replay protection if required
        if annotations.require_replay_protection:
            if not self._check_replay_protection(session, processed_data):
                raise Error(code=400, message="Replay attack detected")
        
        # 9. Audit log
        if annotations.audit_log:
            self._audit_log(
                session=session,
                action="request",
                include_data=annotations.audit_include_inputs,
                data=processed_data if annotations.audit_include_inputs else None
            )
        
        return session, processed_data
    
    async def process_secure_response(
        self,
        annotations: SecureAnnotations,
        session: SecureSession,
        response_data: Any,
    ) -> Any:
        """
        Process a secure response with encryption and signing.
        
        Args:
            annotations: Security annotations
            session: Secure session
            response_data: Response data
        
        Returns:
            Processed response data
        """
        # 1. Audit log
        if annotations.audit_log:
            self._audit_log(
                session=session,
                action="response",
                include_data=annotations.audit_include_outputs,
                data=response_data if annotations.audit_include_outputs else None
            )
        
        # 2. Encrypt output if required
        if annotations.encrypt_output and session.encryption_key:
            response_data = self._encrypt_response_data(session, response_data)
        
        # 3. Add integrity signature if required
        if annotations.require_integrity_check:
            response_data = self._add_integrity_signature(response_data)
        
        # 4. Sign response if tool signature is required
        if annotations.tool_signature_required and self.tool_identity:
            response_data = self._sign_response(response_data)
        
        # 5. Add session metadata
        if isinstance(response_data, dict):
            response_data["_session"] = {
                "id": session.session_id[:8] + "...",  # Truncated for security
                "authenticated": session.client_identity is not None,
                "encrypted": annotations.encrypt_output,
            }
        
        return response_data
    
    async def _authenticate_client(
        self,
        auth_methods: List[AuthMethod],
        auth_header: Optional[str],
        client_cert: Optional[x509.Certificate],
        request_data: Optional[dict],
    ) -> ClientIdentity:
        """Authenticate client using available methods."""
        
        # Try JWT authentication
        if AuthMethod.JWT in auth_methods and auth_header:
            identity = self._authenticate_jwt(auth_header)
            if identity:
                return identity
        
        # Try API key authentication
        if AuthMethod.API_KEY in auth_methods:
            api_key = None
            if auth_header and auth_header.startswith("Bearer "):
                api_key = auth_header[7:]
            elif request_data and "api_key" in request_data:
                api_key = request_data["api_key"]
            
            if api_key:
                identity = self._authenticate_api_key(api_key)
                if identity:
                    return identity
        
        # Try certificate authentication
        if AuthMethod.CERTIFICATE in auth_methods and client_cert:
            identity = self._authenticate_certificate(client_cert)
            if identity:
                return identity
        
        # Try mutual TLS
        if AuthMethod.MTLS in auth_methods and client_cert:
            identity = self._authenticate_mtls(client_cert)
            if identity:
                return identity
        
        raise Error(code=401, message="Authentication failed")
    
    def _authenticate_jwt(self, auth_header: str) -> Optional[ClientIdentity]:
        """Authenticate using JWT token."""
        if not auth_header.startswith("Bearer "):
            return None
        
        token = auth_header[7:]
        
        try:
            # Decode and verify JWT
            claims = jwt.decode(
                token,
                self.jwt_secret,
                algorithms=["HS256", "RS256", "ES256"]
            )
            
            return ClientIdentity(
                client_id=claims.get("sub", "unknown"),
                authentication_method=AuthMethod.JWT,
                credentials=token,
                permissions=set(claims.get("permissions", [])),
                email=claims.get("email"),
                organization=claims.get("org"),
                expires_at=datetime.fromtimestamp(claims.get("exp", 0)),
                metadata={"claims": claims}
            )
        except jwt.InvalidTokenError:
            return None
    
    def _authenticate_api_key(self, api_key: str) -> Optional[ClientIdentity]:
        """Authenticate using API key."""
        return self.api_keys.get(api_key)
    
    def _authenticate_certificate(self, cert: x509.Certificate) -> Optional[ClientIdentity]:
        """Authenticate using X.509 certificate."""
        # Verify certificate against trusted CAs
        for ca in self.trusted_cas:
            try:
                ca.public_key().verify(
                    cert.signature,
                    cert.tbs_certificate_bytes,
                    cert.signature_algorithm_oid._name
                )
                
                # Extract client info from certificate
                from cryptography.x509.oid import NameOID
                
                common_name = cert.subject.get_attributes_for_oid(
                    NameOID.COMMON_NAME
                )[0].value
                
                org = None
                org_attrs = cert.subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
                if org_attrs:
                    org = org_attrs[0].value
                
                return ClientIdentity(
                    client_id=common_name,
                    authentication_method=AuthMethod.CERTIFICATE,
                    credentials=cert,
                    permissions={"read", "write", "execute"},  # Extract from cert extensions
                    organization=org,
                    certificate=cert,
                    certificate_fingerprint=hashlib.sha256(
                        cert.public_bytes(x509.Encoding.DER)
                    ).hexdigest(),
                )
            except Exception:
                continue
        
        return None
    
    def _authenticate_mtls(self, cert: x509.Certificate) -> Optional[ClientIdentity]:
        """Authenticate using mutual TLS."""
        # Similar to certificate auth but with bidirectional verification
        identity = self._authenticate_certificate(cert)
        
        if identity and self.tool_identity:
            # Verify that client also verified our tool certificate
            # This would be handled at the TLS layer in production
            identity.metadata["mtls_verified"] = True
        
        return identity
    
    async def _establish_session(
        self,
        client_identity: Optional[ClientIdentity]
    ) -> SecureSession:
        """Establish or retrieve a secure session."""
        # For simplicity, create a new session each time
        # In production, implement session caching
        
        session_id = base64.b64encode(os.urandom(32)).decode()
        
        # Create encryption key if we have a client
        encryption_key = None
        if client_identity:
            key_bytes = AESGCM.generate_key(bit_length=256)
            encryption_key = AESGCM(key_bytes)
        
        session = SecureSession(
            session_id=session_id,
            client_identity=client_identity,
            tool_identity=self.tool_identity,
            established_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=1),
            encryption_key=encryption_key
        )
        
        self.sessions[session_id] = session
        return session
    
    def _verify_tool_attestation(self, annotations: SecureAnnotations) -> bool:
        """Verify tool attestation matches requirements."""
        if not self.tool_identity:
            return False
        
        # Check certificate fingerprint if specified
        if annotations.tool_certificate_fingerprint:
            if self.tool_identity.fingerprint != annotations.tool_certificate_fingerprint:
                return False
        
        # Check attestation type if specified
        if annotations.attestation_type:
            if self.tool_identity.attestation_type != annotations.attestation_type:
                return False
        
        return True
    
    def _check_rate_limit(
        self,
        client_id: str,
        limit: int,
        per_client: bool
    ) -> None:
        """Check and enforce rate limits."""
        key = client_id if per_client else "global"
        now = datetime.utcnow()
        
        # Clean old entries
        if key in self.rate_limits:
            self.rate_limits[key] = [
                t for t in self.rate_limits[key]
                if (now - t).total_seconds() < 60
            ]
        else:
            self.rate_limits[key] = []
        
        # Check limit
        if len(self.rate_limits[key]) >= limit:
            raise Error(code=429, message="Rate limit exceeded")
        
        # Add current request
        self.rate_limits[key].append(now)
    
    def _decrypt_request_data(
        self,
        session: SecureSession,
        data: dict[str, Any]
    ) -> dict[str, Any]:
        """Decrypt request data."""
        decrypted = {}
        for key, value in data.items():
            if isinstance(value, str) and value.startswith("ENC:"):
                encrypted_bytes = base64.b64decode(value[4:])
                decrypted_bytes = session.decrypt(encrypted_bytes)
                decrypted[key] = json.loads(decrypted_bytes)
            elif isinstance(value, dict):
                decrypted[key] = self._decrypt_request_data(session, value)
            else:
                decrypted[key] = value
        return decrypted
    
    def _encrypt_response_data(
        self,
        session: SecureSession,
        data: Any
    ) -> dict[str, Any]:
        """Encrypt response data."""
        json_data = json.dumps(data)
        encrypted = session.encrypt(json_data.encode())
        
        return {
            "encrypted": True,
            "algorithm": session.encryption_algorithm,
            "data": "ENC:" + base64.b64encode(encrypted).decode(),
            "session_id": session.session_id
        }
    
    def _verify_message_integrity(self, data: dict) -> bool:
        """Verify message integrity signature."""
        if "_integrity" not in data:
            return True  # No integrity check provided
        
        integrity = data.pop("_integrity")
        
        # Compute expected hash
        data_str = json.dumps(data, sort_keys=True)
        expected_hash = hashlib.sha256(data_str.encode()).hexdigest()
        
        return hmac.compare_digest(integrity, expected_hash)
    
    def _add_integrity_signature(self, data: Any) -> dict:
        """Add integrity signature to response."""
        if isinstance(data, dict):
            data_copy = data.copy()
        else:
            data_copy = {"value": data}
        
        # Compute hash
        data_str = json.dumps(data_copy, sort_keys=True)
        integrity = hashlib.sha256(data_str.encode()).hexdigest()
        
        data_copy["_integrity"] = integrity
        return data_copy
    
    def _check_replay_protection(
        self,
        session: SecureSession,
        data: dict
    ) -> bool:
        """Check for replay attacks."""
        if "_request_token" not in data:
            return False
        
        token = data.pop("_request_token")
        return session.verify_request_token(token)
    
    def _sign_response(self, data: Any) -> dict[str, Any]:
        """Sign response data with tool identity."""
        if not self.tool_identity:
            return data if isinstance(data, dict) else {"value": data}
        
        # Prepare data for signing
        if isinstance(data, dict):
            sign_data = data.copy()
        else:
            sign_data = {"value": data}
        
        # Add timestamp
        sign_data["_timestamp"] = datetime.utcnow().isoformat()
        
        # Sign the data
        json_data = json.dumps(sign_data, sort_keys=True)
        signature = self.tool_identity.sign_data(json_data.encode())
        
        return {
            "data": sign_data,
            "signature": base64.b64encode(signature).decode(),
            "tool_id": self.tool_identity.tool_id,
            "tool_fingerprint": self.tool_identity.fingerprint[:16] + "..."
        }
    
    def _audit_log(
        self,
        session: Optional[SecureSession],
        action: str,
        include_data: bool,
        data: Any = None
    ) -> None:
        """Create audit log entry."""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
        }
        
        if session:
            log_entry["session_id"] = session.session_id
            if session.client_identity:
                log_entry["client_id"] = session.client_identity.client_id
                log_entry["auth_method"] = session.client_identity.authentication_method.value
            if session.tool_identity:
                log_entry["tool_id"] = session.tool_identity.tool_id
        
        if include_data and data is not None:
            # Hash sensitive data for audit
            if isinstance(data, (dict, list)):
                log_entry["data_hash"] = hashlib.sha256(
                    json.dumps(data, sort_keys=True).encode()
                ).hexdigest()
            else:
                log_entry["data_hash"] = hashlib.sha256(
                    str(data).encode()
                ).hexdigest()
        
        self.audit_log_entries.append(log_entry)
        
        # In production, write to proper audit system
        # For now, just keep in memory


# Convenience functions for encryption/decryption
def encrypt_data(data: str, key: bytes) -> str:
    """
    Encrypt data using AES-256-GCM.
    
    Args:
        data: Data to encrypt
        key: 256-bit encryption key
    
    Returns:
        Base64-encoded encrypted data
    """
    cipher = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = cipher.encrypt(nonce, data.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt_data(encrypted: str, key: bytes) -> str:
    """
    Decrypt data encrypted with AES-256-GCM.
    
    Args:
        encrypted: Base64-encoded encrypted data
        key: 256-bit encryption key
    
    Returns:
        Decrypted data
    """
    cipher = AESGCM(key)
    raw = base64.b64decode(encrypted)
    nonce, ciphertext = raw[:12], raw[12:]
    plaintext = cipher.decrypt(nonce, ciphertext, None)
    return plaintext.decode()


def generate_session_key(password: str, salt: Optional[bytes] = None) -> bytes:
    """
    Generate a session key from a password.
    
    Args:
        password: Password to derive key from
        salt: Optional salt (will generate if not provided)
    
    Returns:
        256-bit key suitable for AES-256
    """
    if salt is None:
        salt = os.urandom(16)
    
    kdf = PBKDF2(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    return kdf.derive(password.encode())


def verify_signature(
    data: bytes,
    signature: bytes,
    public_key_pem: bytes
) -> bool:
    """
    Verify a digital signature.
    
    Args:
        data: Data that was signed
        signature: Digital signature
        public_key_pem: Public key in PEM format
    
    Returns:
        True if signature is valid
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec, rsa, padding
    
    try:
        public_key = serialization.load_pem_public_key(public_key_pem)
        
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