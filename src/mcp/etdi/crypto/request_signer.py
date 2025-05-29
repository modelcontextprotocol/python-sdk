"""
Request signing and verification for ETDI
"""

import json
import base64
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.exceptions import InvalidSignature
import logging

from .key_manager import KeyManager, KeyPair
from ..exceptions import ETDIError, SignatureError

logger = logging.getLogger(__name__)


class RequestSigner:
    """
    Signs ETDI requests with cryptographic signatures
    """
    
    def __init__(self, key_manager: KeyManager, key_id: str):
        """
        Initialize request signer
        
        Args:
            key_manager: Key manager instance
            key_id: Key ID to use for signing
        """
        self.key_manager = key_manager
        self.key_id = key_id
        self._key_pair: Optional[KeyPair] = None
    
    def _get_key_pair(self) -> KeyPair:
        """Get or load the key pair"""
        if not self._key_pair:
            self._key_pair = self.key_manager.get_or_create_key_pair(self.key_id)
        return self._key_pair
    
    def sign_request(
        self, 
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Optional[str] = None,
        timestamp: Optional[datetime] = None
    ) -> Dict[str, str]:
        """
        Sign an HTTP request
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            headers: Request headers
            body: Request body (if any)
            timestamp: Request timestamp (default: now)
            
        Returns:
            Dictionary with signature headers to add to request
        """
        if not timestamp:
            timestamp = datetime.utcnow()
        
        # Create canonical request string
        canonical_request = self._create_canonical_request(
            method, url, headers, body, timestamp
        )
        
        # Sign the canonical request
        signature = self._sign_string(canonical_request)
        
        # Create signature headers
        signature_headers = {
            'X-ETDI-Signature': signature,
            'X-ETDI-Key-ID': self.key_id,
            'X-ETDI-Timestamp': timestamp.isoformat() + 'Z',
            'X-ETDI-Algorithm': 'RS256'
        }
        
        logger.debug(f"Signed request with key {self.key_id}")
        return signature_headers
    
    def _create_canonical_request(
        self,
        method: str,
        url: str, 
        headers: Dict[str, str],
        body: Optional[str],
        timestamp: datetime
    ) -> str:
        """
        Create canonical request string for signing
        
        This follows a similar pattern to AWS Signature Version 4
        """
        # Parse URL components
        from urllib.parse import urlparse, parse_qs
        parsed_url = urlparse(url)
        
        # Canonical method
        canonical_method = method.upper()
        
        # Canonical URI (path)
        canonical_uri = parsed_url.path or '/'
        
        # Canonical query string
        query_params = parse_qs(parsed_url.query, keep_blank_values=True)
        sorted_params = []
        for key in sorted(query_params.keys()):
            for value in sorted(query_params[key]):
                sorted_params.append(f"{key}={value}")
        canonical_query_string = '&'.join(sorted_params)
        
        # Canonical headers (only include signed headers)
        signed_headers = ['host', 'content-type', 'x-etdi-timestamp']
        canonical_headers = []
        
        # Add host header if not present
        if 'host' not in headers:
            headers = dict(headers)  # Don't modify original
            headers['host'] = parsed_url.netloc
        
        # Add timestamp header
        headers['x-etdi-timestamp'] = timestamp.isoformat() + 'Z'
        
        for header_name in signed_headers:
            header_value = headers.get(header_name, headers.get(header_name.title(), ''))
            if header_value:
                canonical_headers.append(f"{header_name.lower()}:{header_value.strip()}")
        
        canonical_headers_string = '\n'.join(canonical_headers)
        signed_headers_string = ';'.join(signed_headers)
        
        # Payload hash
        if body:
            payload_hash = hashlib.sha256(body.encode('utf-8')).hexdigest()
        else:
            payload_hash = hashlib.sha256(b'').hexdigest()
        
        # Combine into canonical request
        canonical_request = '\n'.join([
            canonical_method,
            canonical_uri,
            canonical_query_string,
            canonical_headers_string,
            '',  # Empty line after headers
            signed_headers_string,
            payload_hash
        ])
        
        logger.debug(f"Canonical request:\n{canonical_request}")
        return canonical_request
    
    def _sign_string(self, string_to_sign: str) -> str:
        """Sign a string using RSA-SHA256"""
        key_pair = self._get_key_pair()
        
        # Hash the string
        digest = hashes.Hash(hashes.SHA256())
        digest.update(string_to_sign.encode('utf-8'))
        hashed_string = digest.finalize()
        
        # Sign the hash
        signature = key_pair.private_key.sign(
            hashed_string,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        
        # Return base64-encoded signature
        return base64.b64encode(signature).decode('utf-8')
    
    def sign_tool_invocation(
        self,
        tool_id: str,
        parameters: Dict[str, Any],
        timestamp: Optional[datetime] = None
    ) -> Dict[str, str]:
        """
        Sign a tool invocation request
        
        Args:
            tool_id: Tool identifier
            parameters: Tool parameters
            timestamp: Invocation timestamp
            
        Returns:
            Signature headers
        """
        if not timestamp:
            timestamp = datetime.utcnow()
        
        # Create invocation payload
        payload = {
            'tool_id': tool_id,
            'parameters': parameters,
            'timestamp': timestamp.isoformat() + 'Z'
        }
        
        # Serialize payload deterministically
        payload_json = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        
        # Sign the payload
        signature = self._sign_string(payload_json)
        
        return {
            'X-ETDI-Tool-Signature': signature,
            'X-ETDI-Key-ID': self.key_id,
            'X-ETDI-Timestamp': timestamp.isoformat() + 'Z',
            'X-ETDI-Algorithm': 'RS256'
        }


class SignatureVerifier:
    """
    Verifies ETDI request signatures
    """
    
    def __init__(self, key_manager: KeyManager):
        """
        Initialize signature verifier
        
        Args:
            key_manager: Key manager for loading public keys
        """
        self.key_manager = key_manager
        self._public_keys: Dict[str, rsa.RSAPublicKey] = {}
    
    def verify_request_signature(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Optional[str] = None,
        max_age_seconds: int = 300
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify request signature
        
        Args:
            method: HTTP method
            url: Request URL
            headers: Request headers
            body: Request body
            max_age_seconds: Maximum age of request in seconds
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            # Extract signature headers
            signature = headers.get('X-ETDI-Signature')
            key_id = headers.get('X-ETDI-Key-ID')
            timestamp_str = headers.get('X-ETDI-Timestamp')
            algorithm = headers.get('X-ETDI-Algorithm', 'RS256')
            
            if not all([signature, key_id, timestamp_str]):
                return False, "Missing required signature headers"
            
            if algorithm != 'RS256':
                return False, f"Unsupported signature algorithm: {algorithm}"
            
            # Parse timestamp
            try:
                timestamp = datetime.fromisoformat(timestamp_str.rstrip('Z'))
            except ValueError:
                return False, "Invalid timestamp format"
            
            # Check timestamp freshness
            age = (datetime.utcnow() - timestamp).total_seconds()
            if age > max_age_seconds:
                return False, f"Request too old: {age}s > {max_age_seconds}s"
            
            if age < -60:  # Allow 1 minute clock skew
                return False, f"Request from future: {age}s"
            
            # Get public key
            public_key = self._get_public_key(key_id)
            if not public_key:
                return False, f"Unknown key ID: {key_id}"
            
            # Recreate canonical request
            signer = RequestSigner(self.key_manager, key_id)
            canonical_request = signer._create_canonical_request(
                method, url, headers, body, timestamp
            )
            
            # Verify signature
            is_valid = self._verify_signature(canonical_request, signature, public_key)
            
            if is_valid:
                logger.debug(f"Request signature verified for key {key_id}")
                return True, None
            else:
                return False, "Invalid signature"
                
        except Exception as e:
            logger.error(f"Signature verification error: {e}")
            return False, f"Verification error: {e}"
    
    def verify_tool_invocation_signature(
        self,
        tool_id: str,
        parameters: Dict[str, Any],
        headers: Dict[str, str],
        max_age_seconds: int = 300
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify tool invocation signature
        
        Args:
            tool_id: Tool identifier
            parameters: Tool parameters
            headers: Request headers with signature
            max_age_seconds: Maximum age of request
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            signature = headers.get('X-ETDI-Tool-Signature')
            key_id = headers.get('X-ETDI-Key-ID')
            timestamp_str = headers.get('X-ETDI-Timestamp')
            
            if not all([signature, key_id, timestamp_str]):
                return False, "Missing required signature headers"
            
            # Parse timestamp
            timestamp = datetime.fromisoformat(timestamp_str.rstrip('Z'))
            
            # Check freshness
            age = (datetime.utcnow() - timestamp).total_seconds()
            if age > max_age_seconds:
                return False, f"Request too old: {age}s"
            
            # Recreate payload
            payload = {
                'tool_id': tool_id,
                'parameters': parameters,
                'timestamp': timestamp_str
            }
            payload_json = json.dumps(payload, sort_keys=True, separators=(',', ':'))
            
            # Get public key and verify
            public_key = self._get_public_key(key_id)
            if not public_key:
                return False, f"Unknown key ID: {key_id}"
            
            is_valid = self._verify_signature(payload_json, signature, public_key)
            return is_valid, None if is_valid else "Invalid signature"
            
        except Exception as e:
            return False, f"Verification error: {e}"
    
    def _get_public_key(self, key_id: str) -> Optional[rsa.RSAPublicKey]:
        """Get public key for verification"""
        if key_id in self._public_keys:
            return self._public_keys[key_id]
        
        # Try to load from key manager
        key_pair = self.key_manager.load_key_pair(key_id)
        if key_pair:
            self._public_keys[key_id] = key_pair.public_key
            return key_pair.public_key
        
        return None
    
    def _verify_signature(
        self, 
        message: str, 
        signature_b64: str, 
        public_key: rsa.RSAPublicKey
    ) -> bool:
        """Verify RSA signature"""
        try:
            # Decode signature
            signature = base64.b64decode(signature_b64)
            
            # Hash message
            digest = hashes.Hash(hashes.SHA256())
            digest.update(message.encode('utf-8'))
            hashed_message = digest.finalize()
            
            # Verify signature
            public_key.verify(
                signature,
                hashed_message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            return True
            
        except InvalidSignature:
            return False
        except Exception as e:
            logger.error(f"Signature verification error: {e}")
            return False
    
    def add_trusted_public_key(self, key_id: str, public_key_pem: str) -> None:
        """
        Add a trusted public key for verification
        
        Args:
            key_id: Key identifier
            public_key_pem: Public key in PEM format
        """
        try:
            public_key = serialization.load_pem_public_key(public_key_pem.encode('utf-8'))
            if isinstance(public_key, rsa.RSAPublicKey):
                self._public_keys[key_id] = public_key
                logger.info(f"Added trusted public key: {key_id}")
            else:
                raise ValueError("Only RSA public keys are supported")
        except Exception as e:
            logger.error(f"Failed to add public key {key_id}: {e}")
            raise