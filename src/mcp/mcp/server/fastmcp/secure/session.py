"""
Session management for secure MCP operations.

Handles secure session establishment, key exchange, and session lifecycle.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, dh
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
from cryptography.hazmat.primitives.asymmetric.types import PublicKeyTypes

from .identity import ClientIdentity, ToolIdentity


@dataclass
class SecureSession:
    """
    Represents a secure session between a client and tool.
    
    Supports:
    - Mutual authentication
    - Key exchange and encryption
    - Session binding and replay protection
    """
    
    session_id: str
    client_identity: Optional[ClientIdentity]
    tool_identity: Optional[ToolIdentity]
    established_at: datetime
    expires_at: datetime
    
    # Encryption
    encryption_algorithm: str = "AES-256-GCM"  # or "ChaCha20-Poly1305"
    encryption_key: Optional[AESGCM | ChaCha20Poly1305] = None
    client_public_key: Optional[PublicKeyTypes] = None
    server_public_key: Optional[PublicKeyTypes] = None
    
    # Session binding
    client_ip: Optional[str] = None
    client_fingerprint: Optional[str] = None
    bound_to_client: bool = False
    
    # Replay protection
    nonce_counter: int = 0
    used_nonces: set[str] = field(default_factory=set)
    max_nonce_age_seconds: int = 300
    
    # Rate limiting
    request_count: int = 0
    last_request_at: Optional[datetime] = None
    
    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def is_valid(self) -> bool:
        """Check if session is still valid."""
        now = datetime.utcnow()
        
        # Check expiration
        if now > self.expires_at:
            return False
        
        # Check client identity expiration
        if self.client_identity and self.client_identity.is_expired():
            return False
        
        return True
    
    def is_bound_to(self, client_ip: str, client_fingerprint: str) -> bool:
        """
        Check if session is bound to the requesting client.
        
        Args:
            client_ip: Client IP address
            client_fingerprint: Client fingerprint (e.g., TLS fingerprint)
        
        Returns:
            True if session binding matches
        """
        if not self.bound_to_client:
            return True
        
        if self.client_ip and self.client_ip != client_ip:
            return False
        
        if self.client_fingerprint and self.client_fingerprint != client_fingerprint:
            return False
        
        return True
    
    def encrypt(self, data: bytes, associated_data: Optional[bytes] = None) -> bytes:
        """
        Encrypt data using session key.
        
        Args:
            data: Data to encrypt
            associated_data: Additional authenticated data
        
        Returns:
            Encrypted data with nonce prepended
        """
        if not self.encryption_key:
            raise ValueError("No encryption key established")
        
        nonce = os.urandom(12)  # 96-bit nonce for AES-GCM
        ciphertext = self.encryption_key.encrypt(nonce, data, associated_data)
        
        return nonce + ciphertext
    
    def decrypt(
        self,
        encrypted_data: bytes,
        associated_data: Optional[bytes] = None
    ) -> bytes:
        """
        Decrypt data using session key.
        
        Args:
            encrypted_data: Encrypted data with nonce prepended
            associated_data: Additional authenticated data
        
        Returns:
            Decrypted data
        """
        if not self.encryption_key:
            raise ValueError("No encryption key established")
        
        nonce, ciphertext = encrypted_data[:12], encrypted_data[12:]
        
        # Check for nonce reuse (replay protection)
        nonce_b64 = base64.b64encode(nonce).decode()
        if nonce_b64 in self.used_nonces:
            raise ValueError("Nonce reuse detected - possible replay attack")
        
        self.used_nonces.add(nonce_b64)
        self.nonce_counter += 1
        
        return self.encryption_key.decrypt(nonce, ciphertext, associated_data)
    
    def generate_request_token(self) -> str:
        """
        Generate a request token for replay protection.
        
        Returns:
            Base64-encoded request token
        """
        timestamp = datetime.utcnow().isoformat()
        nonce = secrets.token_bytes(16)
        
        token_data = f"{self.session_id}:{timestamp}:{base64.b64encode(nonce).decode()}"
        
        # Sign the token
        if self.encryption_key and isinstance(self.encryption_key, AESGCM):
            # Use HMAC with part of the session key
            key_bytes = self.encryption_key._key[:16]  # Use first 16 bytes for HMAC
            signature = hmac.new(key_bytes, token_data.encode(), hashlib.sha256).digest()
            
            return base64.b64encode(
                token_data.encode() + signature
            ).decode()
        
        return base64.b64encode(token_data.encode()).decode()
    
    def verify_request_token(self, token: str) -> bool:
        """
        Verify a request token for replay protection.
        
        Args:
            token: Request token to verify
        
        Returns:
            True if token is valid and fresh
        """
        try:
            decoded = base64.b64decode(token)
            
            if self.encryption_key and isinstance(self.encryption_key, AESGCM):
                # Split token and signature
                token_data = decoded[:-32]
                signature = decoded[-32:]
                
                # Verify signature
                key_bytes = self.encryption_key._key[:16]
                expected_sig = hmac.new(key_bytes, token_data, hashlib.sha256).digest()
                
                if not hmac.compare_digest(signature, expected_sig):
                    return False
            else:
                token_data = decoded
            
            # Parse token
            parts = token_data.decode().split(":")
            if len(parts) != 3:
                return False
            
            session_id, timestamp_str, nonce_b64 = parts
            
            # Verify session ID
            if session_id != self.session_id:
                return False
            
            # Check timestamp freshness
            timestamp = datetime.fromisoformat(timestamp_str)
            age = (datetime.utcnow() - timestamp).total_seconds()
            
            if age > self.max_nonce_age_seconds:
                return False
            
            # Check nonce uniqueness
            if nonce_b64 in self.used_nonces:
                return False
            
            self.used_nonces.add(nonce_b64)
            
            return True
            
        except Exception:
            return False
    
    def rotate_session_key(self) -> None:
        """Rotate the session encryption key."""
        if not self.encryption_key:
            return
        
        # Derive new key from old key
        if isinstance(self.encryption_key, AESGCM):
            old_key = self.encryption_key._key
            
            # Use HKDF to derive new key
            hkdf = HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=None,
                info=b'session-key-rotation',
            )
            new_key = hkdf.derive(old_key + self.session_id.encode())
            
            self.encryption_key = AESGCM(new_key)
        
        # Clear nonce history on key rotation
        self.used_nonces.clear()
        self.nonce_counter = 0


class SessionManager:
    """
    Manages secure sessions for MCP operations.
    """
    
    def __init__(
        self,
        tool_identity: Optional[ToolIdentity] = None,
        session_timeout_minutes: int = 60,
        max_sessions_per_client: int = 10,
    ):
        self.tool_identity = tool_identity
        self.session_timeout_minutes = session_timeout_minutes
        self.max_sessions_per_client = max_sessions_per_client
        
        # Session storage
        self.sessions: Dict[str, SecureSession] = {}
        self.client_sessions: Dict[str, list[str]] = {}  # client_id -> [session_ids]
        
        # DH parameters for key exchange
        self._dh_parameters = None
        self._ecdh_curve = ec.SECP256R1()
    
    def create_session(
        self,
        client_identity: Optional[ClientIdentity] = None,
        encryption_algorithm: str = "AES-256-GCM",
        bind_to_client: bool = False,
        client_ip: Optional[str] = None,
        client_fingerprint: Optional[str] = None,
    ) -> SecureSession:
        """
        Create a new secure session.
        
        Args:
            client_identity: Authenticated client identity
            encryption_algorithm: Encryption algorithm to use
            bind_to_client: Whether to bind session to client
            client_ip: Client IP for session binding
            client_fingerprint: Client fingerprint for session binding
        
        Returns:
            New SecureSession instance
        """
        # Generate session ID
        session_id = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
        
        # Check session limit per client
        if client_identity:
            client_id = client_identity.client_id
            if client_id in self.client_sessions:
                if len(self.client_sessions[client_id]) >= self.max_sessions_per_client:
                    # Remove oldest session
                    oldest_session_id = self.client_sessions[client_id][0]
                    self.revoke_session(oldest_session_id)
        
        # Create session
        session = SecureSession(
            session_id=session_id,
            client_identity=client_identity,
            tool_identity=self.tool_identity,
            established_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(minutes=self.session_timeout_minutes),
            encryption_algorithm=encryption_algorithm,
            bound_to_client=bind_to_client,
            client_ip=client_ip,
            client_fingerprint=client_fingerprint,
        )
        
        # Store session
        self.sessions[session_id] = session
        
        # Track client sessions
        if client_identity:
            client_id = client_identity.client_id
            if client_id not in self.client_sessions:
                self.client_sessions[client_id] = []
            self.client_sessions[client_id].append(session_id)
        
        return session
    
    def get_session(self, session_id: str) -> Optional[SecureSession]:
        """
        Get a session by ID.
        
        Args:
            session_id: Session ID
        
        Returns:
            SecureSession if found and valid
        """
        session = self.sessions.get(session_id)
        
        if session and session.is_valid():
            return session
        
        # Remove invalid session
        if session:
            self.revoke_session(session_id)
        
        return None
    
    def revoke_session(self, session_id: str) -> None:
        """
        Revoke a session.
        
        Args:
            session_id: Session ID to revoke
        """
        session = self.sessions.pop(session_id, None)
        
        if session and session.client_identity:
            # Remove from client sessions
            client_id = session.client_identity.client_id
            if client_id in self.client_sessions:
                self.client_sessions[client_id] = [
                    sid for sid in self.client_sessions[client_id]
                    if sid != session_id
                ]
    
    def perform_ecdh_key_exchange(
        self,
        session: SecureSession,
        client_public_key_pem: bytes
    ) -> bytes:
        """
        Perform ECDH key exchange to establish session key.
        
        Args:
            session: Session to establish key for
            client_public_key_pem: Client's public key in PEM format
        
        Returns:
            Server's public key in PEM format
        """
        # Generate server's ephemeral key pair
        server_private_key = ec.generate_private_key(self._ecdh_curve)
        server_public_key = server_private_key.public_key()
        
        # Load client's public key
        client_public_key = serialization.load_pem_public_key(client_public_key_pem)
        
        # Perform ECDH to get shared secret
        shared_secret = server_private_key.exchange(
            ec.ECDH(),
            client_public_key
        )
        
        # Derive session key using HKDF
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,  # 256-bit key
            salt=session.session_id.encode()[:16],  # Use session ID as salt
            info=b'mcp-session-key',
        )
        session_key = hkdf.derive(shared_secret)
        
        # Create cipher based on algorithm
        if session.encryption_algorithm == "ChaCha20-Poly1305":
            session.encryption_key = ChaCha20Poly1305(session_key)
        else:  # Default to AES-256-GCM
            session.encryption_key = AESGCM(session_key)
        
        # Store public keys
        session.client_public_key = client_public_key
        session.server_public_key = server_public_key
        
        # Return server's public key
        return server_public_key.public_key_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
    
    def establish_pre_shared_key(
        self,
        session: SecureSession,
        pre_shared_key: bytes
    ) -> None:
        """
        Establish session key from pre-shared key.
        
        Args:
            session: Session to establish key for
            pre_shared_key: Pre-shared key
        """
        # Derive session key from PSK using PBKDF2
        kdf = PBKDF2(
            algorithm=hashes.SHA256(),
            length=32,
            salt=session.session_id.encode()[:16],
            iterations=100000,
        )
        session_key = kdf.derive(pre_shared_key)
        
        # Create cipher
        if session.encryption_algorithm == "ChaCha20-Poly1305":
            session.encryption_key = ChaCha20Poly1305(session_key)
        else:
            session.encryption_key = AESGCM(session_key)
    
    def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired sessions.
        
        Returns:
            Number of sessions removed
        """
        expired_sessions = [
            session_id for session_id, session in self.sessions.items()
            if not session.is_valid()
        ]
        
        for session_id in expired_sessions:
            self.revoke_session(session_id)
        
        return len(expired_sessions)