"""
Cryptographic key management for ETDI request signing
"""

import os
import json
import base64
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
import logging

logger = logging.getLogger(__name__)


@dataclass
class KeyPair:
    """Represents a cryptographic key pair for signing"""
    private_key: rsa.RSAPrivateKey
    public_key: rsa.RSAPublicKey
    key_id: str
    created_at: datetime
    algorithm: str = "RSA-2048"
    expires_at: Optional[datetime] = None
    
    def to_pem(self) -> Tuple[bytes, bytes]:
        """Export keys to PEM format"""
        private_pem = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        
        public_pem = self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
        return private_pem, public_pem
    
    def public_key_fingerprint(self) -> str:
        """Generate fingerprint of public key"""
        public_pem = self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        digest = hashes.Hash(hashes.SHA256())
        digest.update(public_pem)
        return base64.b64encode(digest.finalize()).decode('utf-8')[:16]


class KeyManager:
    """
    Manages cryptographic keys for ETDI request signing
    """
    
    def __init__(self, key_store_path: Optional[str] = None):
        """
        Initialize key manager
        
        Args:
            key_store_path: Path to store keys (default: ~/.etdi/keys)
        """
        self.key_store_path = key_store_path or os.path.expanduser("~/.etdi/keys")
        self._keys: Dict[str, KeyPair] = {}
        self._ensure_key_store_exists()
    
    def _ensure_key_store_exists(self) -> None:
        """Ensure key store directory exists"""
        os.makedirs(self.key_store_path, mode=0o700, exist_ok=True)
    
    def generate_key_pair(
        self, 
        key_id: str, 
        key_size: int = 2048,
        expires_in_days: Optional[int] = 365
    ) -> KeyPair:
        """
        Generate a new RSA key pair
        
        Args:
            key_id: Unique identifier for the key pair
            key_size: RSA key size in bits
            expires_in_days: Key expiration in days (None for no expiration)
            
        Returns:
            Generated key pair
        """
        # Generate RSA key pair
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size
        )
        public_key = private_key.public_key()
        
        # Set expiration
        created_at = datetime.utcnow()
        expires_at = None
        if expires_in_days:
            expires_at = created_at + timedelta(days=expires_in_days)
        
        key_pair = KeyPair(
            private_key=private_key,
            public_key=public_key,
            key_id=key_id,
            created_at=created_at,
            algorithm=f"RSA-{key_size}",
            expires_at=expires_at
        )
        
        # Store the key pair
        self._keys[key_id] = key_pair
        self._save_key_pair(key_pair)
        
        logger.info(f"Generated new key pair: {key_id}")
        return key_pair
    
    def load_key_pair(self, key_id: str) -> Optional[KeyPair]:
        """
        Load a key pair from storage
        
        Args:
            key_id: Key identifier
            
        Returns:
            Key pair if found, None otherwise
        """
        if key_id in self._keys:
            return self._keys[key_id]
        
        # Try to load from disk
        private_key_path = os.path.join(self.key_store_path, f"{key_id}.private.pem")
        public_key_path = os.path.join(self.key_store_path, f"{key_id}.public.pem")
        metadata_path = os.path.join(self.key_store_path, f"{key_id}.metadata.json")
        
        if not all(os.path.exists(p) for p in [private_key_path, public_key_path, metadata_path]):
            return None
        
        try:
            # Load private key
            with open(private_key_path, 'rb') as f:
                private_key = load_pem_private_key(f.read(), password=None)
            
            # Load public key
            with open(public_key_path, 'rb') as f:
                public_key = load_pem_public_key(f.read())
            
            # Load metadata
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
            
            created_at = datetime.fromisoformat(metadata['created_at'])
            expires_at = None
            if metadata.get('expires_at'):
                expires_at = datetime.fromisoformat(metadata['expires_at'])
            
            key_pair = KeyPair(
                private_key=private_key,
                public_key=public_key,
                key_id=key_id,
                created_at=created_at,
                expires_at=expires_at
            )
            
            self._keys[key_id] = key_pair
            logger.info(f"Loaded key pair: {key_id}")
            return key_pair
            
        except Exception as e:
            logger.error(f"Failed to load key pair {key_id}: {e}")
            return None
    
    def _save_key_pair(self, key_pair: KeyPair) -> None:
        """Save key pair to disk"""
        try:
            private_pem, public_pem = key_pair.to_pem()
            
            # Save private key
            private_key_path = os.path.join(self.key_store_path, f"{key_pair.key_id}.private.pem")
            with open(private_key_path, 'wb') as f:
                f.write(private_pem)
            os.chmod(private_key_path, 0o600)  # Restrict access
            
            # Save public key
            public_key_path = os.path.join(self.key_store_path, f"{key_pair.key_id}.public.pem")
            with open(public_key_path, 'wb') as f:
                f.write(public_pem)
            
            # Save metadata
            metadata = {
                'key_id': key_pair.key_id,
                'created_at': key_pair.created_at.isoformat(),
                'expires_at': key_pair.expires_at.isoformat() if key_pair.expires_at else None,
                'fingerprint': key_pair.public_key_fingerprint()
            }
            
            metadata_path = os.path.join(self.key_store_path, f"{key_pair.key_id}.metadata.json")
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            logger.debug(f"Saved key pair to disk: {key_pair.key_id}")
            
        except Exception as e:
            logger.error(f"Failed to save key pair {key_pair.key_id}: {e}")
            raise
    
    def get_or_create_key_pair(self, key_id: str) -> KeyPair:
        """
        Get existing key pair or create new one
        
        Args:
            key_id: Key identifier
            
        Returns:
            Key pair
        """
        key_pair = self.load_key_pair(key_id)
        if key_pair:
            # Check if key is expired
            if key_pair.expires_at and datetime.utcnow() > key_pair.expires_at:
                logger.warning(f"Key pair {key_id} is expired, generating new one")
                return self.generate_key_pair(key_id)
            return key_pair
        
        return self.generate_key_pair(key_id)
    
    def list_keys(self) -> Dict[str, Dict[str, str]]:
        """
        List all available keys with metadata
        
        Returns:
            Dictionary mapping key IDs to metadata
        """
        keys_info = {}
        
        # Check disk for key files
        if os.path.exists(self.key_store_path):
            for filename in os.listdir(self.key_store_path):
                if filename.endswith('.metadata.json'):
                    key_id = filename.replace('.metadata.json', '')
                    metadata_path = os.path.join(self.key_store_path, filename)
                    
                    try:
                        with open(metadata_path, 'r') as f:
                            metadata = json.load(f)
                        
                        keys_info[key_id] = {
                            'created_at': metadata['created_at'],
                            'expires_at': metadata.get('expires_at'),
                            'fingerprint': metadata.get('fingerprint', 'unknown'),
                            'status': 'expired' if (
                                metadata.get('expires_at') and 
                                datetime.fromisoformat(metadata['expires_at']) < datetime.utcnow()
                            ) else 'active'
                        }
                    except Exception as e:
                        logger.warning(f"Failed to read metadata for {key_id}: {e}")
        
        return keys_info
    
    def delete_key_pair(self, key_id: str) -> bool:
        """
        Delete a key pair
        
        Args:
            key_id: Key identifier
            
        Returns:
            True if deleted successfully
        """
        try:
            # Remove from memory
            if key_id in self._keys:
                del self._keys[key_id]
            
            # Remove from disk
            files_to_remove = [
                f"{key_id}.private.pem",
                f"{key_id}.public.pem", 
                f"{key_id}.metadata.json"
            ]
            
            for filename in files_to_remove:
                file_path = os.path.join(self.key_store_path, filename)
                if os.path.exists(file_path):
                    os.remove(file_path)
            
            logger.info(f"Deleted key pair: {key_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete key pair {key_id}: {e}")
            return False
    
    def export_public_key(self, key_id: str) -> Optional[str]:
        """
        Export public key in PEM format for sharing
        
        Args:
            key_id: Key identifier
            
        Returns:
            Public key in PEM format as string
        """
        key_pair = self.load_key_pair(key_id)
        if not key_pair:
            return None
        
        public_pem = key_pair.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
        return public_pem.decode('utf-8')