"""
Key exchange protocols for ETDI request signing
"""

import json
import base64
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum
import logging

from .key_manager import KeyManager
from ..exceptions import ETDIError, KeyExchangeError

logger = logging.getLogger(__name__)


class KeyExchangeProtocol(Enum):
    """Supported key exchange protocols"""
    SIMPLE_EXCHANGE = "simple_exchange"  # Direct public key exchange
    OAUTH_DISCOVERY = "oauth_discovery"  # Discover keys via OAuth provider
    MCP_EXTENSION = "mcp_extension"      # Exchange via MCP protocol extension


@dataclass
class PublicKeyInfo:
    """Public key information for exchange"""
    key_id: str
    public_key_pem: str
    algorithm: str
    created_at: str
    expires_at: Optional[str] = None
    fingerprint: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PublicKeyInfo":
        return cls(**data)


@dataclass
class KeyExchangeRequest:
    """Request for key exchange"""
    requester_id: str
    requester_public_key: PublicKeyInfo
    protocol: KeyExchangeProtocol
    timestamp: str
    nonce: str
    signature: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['protocol'] = self.protocol.value
        data['requester_public_key'] = self.requester_public_key.to_dict()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KeyExchangeRequest":
        data['protocol'] = KeyExchangeProtocol(data['protocol'])
        data['requester_public_key'] = PublicKeyInfo.from_dict(data['requester_public_key'])
        return cls(**data)


@dataclass
class KeyExchangeResponse:
    """Response to key exchange request"""
    responder_id: str
    responder_public_key: PublicKeyInfo
    accepted: bool
    timestamp: str
    nonce: str
    error_message: Optional[str] = None
    signature: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['responder_public_key'] = self.responder_public_key.to_dict()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KeyExchangeResponse":
        data['responder_public_key'] = PublicKeyInfo.from_dict(data['responder_public_key'])
        return cls(**data)


class KeyExchangeManager:
    """
    Manages cryptographic key exchange between ETDI clients and servers
    """
    
    def __init__(self, key_manager: KeyManager, entity_id: str):
        """
        Initialize key exchange manager
        
        Args:
            key_manager: Key manager instance
            entity_id: Unique identifier for this entity (client/server)
        """
        self.key_manager = key_manager
        self.entity_id = entity_id
        self._trusted_keys: Dict[str, PublicKeyInfo] = {}
        self._pending_exchanges: Dict[str, KeyExchangeRequest] = {}
        self._exchange_callbacks: Dict[str, callable] = {}
    
    async def initiate_key_exchange(
        self,
        target_entity_id: str,
        protocol: KeyExchangeProtocol = KeyExchangeProtocol.SIMPLE_EXCHANGE,
        my_key_id: Optional[str] = None
    ) -> KeyExchangeRequest:
        """
        Initiate key exchange with another entity
        
        Args:
            target_entity_id: ID of the entity to exchange keys with
            protocol: Key exchange protocol to use
            my_key_id: Key ID to use (default: entity_id)
            
        Returns:
            Key exchange request
        """
        if not my_key_id:
            my_key_id = self.entity_id
        
        # Get or create our key pair
        key_pair = self.key_manager.get_or_create_key_pair(my_key_id)
        
        # Create public key info
        public_key_pem = self.key_manager.export_public_key(my_key_id)
        if not public_key_pem:
            raise KeyExchangeError(f"Failed to export public key: {my_key_id}")
        
        public_key_info = PublicKeyInfo(
            key_id=my_key_id,
            public_key_pem=public_key_pem,
            algorithm="RS256",
            created_at=key_pair.created_at.isoformat(),
            expires_at=key_pair.expires_at.isoformat() if key_pair.expires_at else None,
            fingerprint=key_pair.public_key_fingerprint(),
            metadata={
                "entity_id": self.entity_id,
                "entity_type": "etdi_client"  # or etdi_server
            }
        )
        
        # Create exchange request
        import secrets
        nonce = secrets.token_urlsafe(32)
        timestamp = datetime.utcnow().isoformat() + 'Z'
        
        request = KeyExchangeRequest(
            requester_id=self.entity_id,
            requester_public_key=public_key_info,
            protocol=protocol,
            timestamp=timestamp,
            nonce=nonce
        )
        
        # Sign the request
        request.signature = await self._sign_exchange_message(request.to_dict(), my_key_id)
        
        # Store pending exchange
        self._pending_exchanges[nonce] = request
        
        logger.info(f"Initiated key exchange with {target_entity_id} using {protocol.value}")
        return request
    
    async def handle_key_exchange_request(
        self,
        request: KeyExchangeRequest,
        auto_accept: bool = False
    ) -> KeyExchangeResponse:
        """
        Handle incoming key exchange request
        
        Args:
            request: Key exchange request
            auto_accept: Whether to automatically accept the request
            
        Returns:
            Key exchange response
        """
        try:
            # Verify request signature if present
            if request.signature:
                is_valid = await self._verify_exchange_signature(
                    request.to_dict(), 
                    request.signature,
                    request.requester_public_key.public_key_pem
                )
                if not is_valid:
                    return self._create_error_response(
                        request, "Invalid request signature"
                    )
            
            # Check if we should accept this exchange
            accepted = auto_accept or await self._should_accept_exchange(request)
            
            if not accepted:
                return self._create_error_response(
                    request, "Key exchange request rejected"
                )
            
            # Get our public key
            my_key_id = self.entity_id
            key_pair = self.key_manager.get_or_create_key_pair(my_key_id)
            public_key_pem = self.key_manager.export_public_key(my_key_id)
            
            if not public_key_pem:
                return self._create_error_response(
                    request, "Failed to export our public key"
                )
            
            # Create our public key info
            our_public_key_info = PublicKeyInfo(
                key_id=my_key_id,
                public_key_pem=public_key_pem,
                algorithm="RS256",
                created_at=key_pair.created_at.isoformat(),
                expires_at=key_pair.expires_at.isoformat() if key_pair.expires_at else None,
                fingerprint=key_pair.public_key_fingerprint(),
                metadata={
                    "entity_id": self.entity_id,
                    "entity_type": "etdi_server"  # or etdi_client
                }
            )
            
            # Create response
            response = KeyExchangeResponse(
                responder_id=self.entity_id,
                responder_public_key=our_public_key_info,
                accepted=True,
                timestamp=datetime.utcnow().isoformat() + 'Z',
                nonce=request.nonce
            )
            
            # Sign the response
            response.signature = await self._sign_exchange_message(
                response.to_dict(), my_key_id
            )
            
            # Store their public key as trusted
            await self._store_trusted_key(request.requester_public_key)
            
            logger.info(f"Accepted key exchange from {request.requester_id}")
            return response
            
        except Exception as e:
            logger.error(f"Error handling key exchange request: {e}")
            return self._create_error_response(request, f"Internal error: {e}")
    
    async def handle_key_exchange_response(
        self,
        response: KeyExchangeResponse
    ) -> bool:
        """
        Handle key exchange response
        
        Args:
            response: Key exchange response
            
        Returns:
            True if exchange completed successfully
        """
        try:
            # Find the original request
            request = self._pending_exchanges.get(response.nonce)
            if not request:
                logger.warning(f"No pending exchange found for nonce: {response.nonce}")
                return False
            
            # Verify response signature if present
            if response.signature:
                is_valid = await self._verify_exchange_signature(
                    response.to_dict(),
                    response.signature,
                    response.responder_public_key.public_key_pem
                )
                if not is_valid:
                    logger.error("Invalid response signature")
                    return False
            
            if not response.accepted:
                logger.warning(f"Key exchange rejected: {response.error_message}")
                return False
            
            # Store their public key as trusted
            await self._store_trusted_key(response.responder_public_key)
            
            # Clean up pending exchange
            del self._pending_exchanges[response.nonce]
            
            # Notify callback if registered
            callback = self._exchange_callbacks.get(response.nonce)
            if callback:
                await callback(response)
                del self._exchange_callbacks[response.nonce]
            
            logger.info(f"Key exchange completed with {response.responder_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error handling key exchange response: {e}")
            return False
    
    def _create_error_response(
        self, 
        request: KeyExchangeRequest, 
        error_message: str
    ) -> KeyExchangeResponse:
        """Create error response"""
        # Create minimal public key info for error response
        dummy_key_info = PublicKeyInfo(
            key_id="error",
            public_key_pem="",
            algorithm="RS256",
            created_at=datetime.utcnow().isoformat()
        )
        
        return KeyExchangeResponse(
            responder_id=self.entity_id,
            responder_public_key=dummy_key_info,
            accepted=False,
            timestamp=datetime.utcnow().isoformat() + 'Z',
            nonce=request.nonce,
            error_message=error_message
        )
    
    async def _should_accept_exchange(self, request: KeyExchangeRequest) -> bool:
        """
        Determine if we should accept a key exchange request
        Override this method to implement custom acceptance logic
        """
        # Basic checks
        try:
            # Check timestamp freshness (within 5 minutes)
            request_time = datetime.fromisoformat(request.timestamp.rstrip('Z'))
            age = (datetime.utcnow() - request_time).total_seconds()
            if age > 300:  # 5 minutes
                logger.warning(f"Key exchange request too old: {age}s")
                return False
            
            # Check if we already have a key for this entity
            if request.requester_id in self._trusted_keys:
                logger.info(f"Already have key for {request.requester_id}, accepting update")
            
            return True
            
        except Exception as e:
            logger.error(f"Error evaluating key exchange request: {e}")
            return False
    
    async def _store_trusted_key(self, public_key_info: PublicKeyInfo) -> None:
        """Store a trusted public key"""
        try:
            # Validate the public key
            from cryptography.hazmat.primitives import serialization
            public_key = serialization.load_pem_public_key(
                public_key_info.public_key_pem.encode('utf-8')
            )
            
            # Store in memory
            entity_id = public_key_info.metadata.get('entity_id', public_key_info.key_id)
            self._trusted_keys[entity_id] = public_key_info
            
            # Optionally persist to disk
            await self._persist_trusted_key(public_key_info)
            
            logger.info(f"Stored trusted key for {entity_id}")
            
        except Exception as e:
            logger.error(f"Failed to store trusted key: {e}")
            raise KeyExchangeError(f"Invalid public key: {e}")
    
    async def _persist_trusted_key(self, public_key_info: PublicKeyInfo) -> None:
        """Persist trusted key to storage"""
        # This could save to a trusted keys file or database
        # For now, we'll just log it
        logger.debug(f"Would persist trusted key: {public_key_info.key_id}")
    
    async def _sign_exchange_message(self, message: Dict[str, Any], key_id: str) -> str:
        """Sign a key exchange message"""
        from .request_signer import RequestSigner
        
        # Create deterministic JSON
        message_json = json.dumps(message, sort_keys=True, separators=(',', ':'))
        
        # Sign using request signer
        signer = RequestSigner(self.key_manager, key_id)
        signature = signer._sign_string(message_json)
        
        return signature
    
    async def _verify_exchange_signature(
        self, 
        message: Dict[str, Any], 
        signature: str,
        public_key_pem: str
    ) -> bool:
        """Verify key exchange message signature"""
        try:
            from .request_signer import SignatureVerifier
            from cryptography.hazmat.primitives import serialization
            
            # Load public key
            public_key = serialization.load_pem_public_key(public_key_pem.encode('utf-8'))
            
            # Create message JSON
            message_json = json.dumps(message, sort_keys=True, separators=(',', ':'))
            
            # Verify signature
            verifier = SignatureVerifier(self.key_manager)
            return verifier._verify_signature(message_json, signature, public_key)
            
        except Exception as e:
            logger.error(f"Signature verification error: {e}")
            return False
    
    def get_trusted_keys(self) -> Dict[str, PublicKeyInfo]:
        """Get all trusted public keys"""
        return self._trusted_keys.copy()
    
    def get_trusted_key(self, entity_id: str) -> Optional[PublicKeyInfo]:
        """Get trusted public key for specific entity"""
        return self._trusted_keys.get(entity_id)
    
    def remove_trusted_key(self, entity_id: str) -> bool:
        """Remove a trusted key"""
        if entity_id in self._trusted_keys:
            del self._trusted_keys[entity_id]
            logger.info(f"Removed trusted key for {entity_id}")
            return True
        return False
    
    def register_exchange_callback(self, nonce: str, callback: callable) -> None:
        """Register callback for key exchange completion"""
        self._exchange_callbacks[nonce] = callback
    
    async def discover_keys_via_oauth(
        self, 
        oauth_provider_url: str,
        access_token: str
    ) -> List[PublicKeyInfo]:
        """
        Discover public keys via OAuth provider's key discovery endpoint
        
        Args:
            oauth_provider_url: OAuth provider base URL
            access_token: Access token for authentication
            
        Returns:
            List of discovered public keys
        """
        # This would implement OAuth-based key discovery
        # Similar to JWKS (JSON Web Key Set) discovery
        logger.info(f"Would discover keys from OAuth provider: {oauth_provider_url}")
        return []
    
    async def exchange_keys_via_mcp(
        self,
        mcp_session,
        target_entity_id: str
    ) -> bool:
        """
        Exchange keys via MCP protocol extension
        
        Args:
            mcp_session: MCP session to use
            target_entity_id: Target entity ID
            
        Returns:
            True if exchange successful
        """
        # This would implement key exchange as an MCP tool/resource
        logger.info(f"Would exchange keys via MCP with {target_entity_id}")
        return False