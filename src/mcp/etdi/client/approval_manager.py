"""
ETDI approval manager for storing and managing user tool approvals
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import hashlib
from cryptography.fernet import Fernet
import base64

from ..types import ToolApprovalRecord, ETDIToolDefinition, Permission
from ..exceptions import ApprovalError, StorageError

logger = logging.getLogger(__name__)


class ApprovalManager:
    """
    Manages tool approval records with secure storage
    """
    
    def __init__(self, storage_path: Optional[str] = None, encryption_key: Optional[bytes] = None):
        """
        Initialize the approval manager
        
        Args:
            storage_path: Path to store approval records (default: ~/.etdi/approvals)
            encryption_key: Encryption key for secure storage (auto-generated if None)
        """
        self.storage_path = Path(storage_path or os.path.expanduser("~/.etdi/approvals"))
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize encryption
        if encryption_key:
            self.encryption_key = encryption_key
        else:
            self.encryption_key = self._get_or_create_encryption_key()
        
        self.cipher = Fernet(self.encryption_key)
        self._lock = asyncio.Lock()
    
    def _get_or_create_encryption_key(self) -> bytes:
        """Get or create encryption key for secure storage"""
        key_file = self.storage_path / ".key"
        
        if key_file.exists():
            try:
                with open(key_file, "rb") as f:
                    return f.read()
            except Exception as e:
                logger.warning(f"Could not read encryption key: {e}, generating new one")
        
        # Generate new key
        key = Fernet.generate_key()
        try:
            with open(key_file, "wb") as f:
                f.write(key)
            # Secure the key file
            os.chmod(key_file, 0o600)
        except Exception as e:
            logger.warning(f"Could not save encryption key: {e}")
        
        return key
    
    async def store_approval(self, record: ToolApprovalRecord) -> None:
        """
        Store a tool approval record
        
        Args:
            record: Tool approval record to store
            
        Raises:
            ApprovalError: If storage fails
        """
        try:
            async with self._lock:
                # Create filename based on tool ID
                filename = self._get_approval_filename(record.tool_id)
                filepath = self.storage_path / filename
                
                # Serialize and encrypt the record
                record_data = record.to_dict()
                record_json = json.dumps(record_data, default=str)
                encrypted_data = self.cipher.encrypt(record_json.encode())
                
                # Write to file
                with open(filepath, "wb") as f:
                    f.write(encrypted_data)
                
                # Secure the file
                os.chmod(filepath, 0o600)
                
                logger.info(f"Stored approval for tool {record.tool_id}")
                
        except Exception as e:
            raise ApprovalError(
                f"Failed to store approval for tool {record.tool_id}: {e}",
                tool_id=record.tool_id,
                operation="store"
            )
    
    async def get_approval(self, tool_id: str) -> Optional[ToolApprovalRecord]:
        """
        Get a tool approval record
        
        Args:
            tool_id: Tool identifier
            
        Returns:
            Tool approval record if found, None otherwise
            
        Raises:
            ApprovalError: If retrieval fails
        """
        try:
            async with self._lock:
                filename = self._get_approval_filename(tool_id)
                filepath = self.storage_path / filename
                
                if not filepath.exists():
                    return None
                
                # Read and decrypt the record
                with open(filepath, "rb") as f:
                    encrypted_data = f.read()
                
                decrypted_data = self.cipher.decrypt(encrypted_data)
                record_data = json.loads(decrypted_data.decode())
                
                # Convert back to ToolApprovalRecord
                record = ToolApprovalRecord.from_dict(record_data)
                
                # Check if approval has expired
                if record.is_expired():
                    logger.info(f"Approval for tool {tool_id} has expired, removing")
                    await self.remove_approval(tool_id)
                    return None
                
                return record
                
        except Exception as e:
            if isinstance(e, ApprovalError):
                raise
            raise ApprovalError(
                f"Failed to get approval for tool {tool_id}: {e}",
                tool_id=tool_id,
                operation="get"
            )
    
    async def remove_approval(self, tool_id: str) -> bool:
        """
        Remove a tool approval record
        
        Args:
            tool_id: Tool identifier
            
        Returns:
            True if approval was removed, False if not found
            
        Raises:
            ApprovalError: If removal fails
        """
        try:
            async with self._lock:
                filename = self._get_approval_filename(tool_id)
                filepath = self.storage_path / filename
                
                if not filepath.exists():
                    return False
                
                filepath.unlink()
                logger.info(f"Removed approval for tool {tool_id}")
                return True
                
        except Exception as e:
            raise ApprovalError(
                f"Failed to remove approval for tool {tool_id}: {e}",
                tool_id=tool_id,
                operation="remove"
            )
    
    async def list_approvals(self) -> List[ToolApprovalRecord]:
        """
        List all stored approval records
        
        Returns:
            List of tool approval records
            
        Raises:
            ApprovalError: If listing fails
        """
        try:
            async with self._lock:
                approvals = []
                
                for filepath in self.storage_path.glob("*.approval"):
                    try:
                        with open(filepath, "rb") as f:
                            encrypted_data = f.read()
                        
                        decrypted_data = self.cipher.decrypt(encrypted_data)
                        record_data = json.loads(decrypted_data.decode())
                        record = ToolApprovalRecord.from_dict(record_data)
                        
                        # Skip expired approvals
                        if not record.is_expired():
                            approvals.append(record)
                        else:
                            # Clean up expired approval
                            filepath.unlink()
                            logger.debug(f"Cleaned up expired approval: {filepath.name}")
                            
                    except Exception as e:
                        logger.warning(f"Could not read approval file {filepath}: {e}")
                        continue
                
                return approvals
                
        except Exception as e:
            raise ApprovalError(f"Failed to list approvals: {e}", operation="list")
    
    async def is_tool_approved(self, tool_id: str) -> bool:
        """
        Check if a tool is approved
        
        Args:
            tool_id: Tool identifier
            
        Returns:
            True if tool is approved and not expired
        """
        try:
            approval = await self.get_approval(tool_id)
            return approval is not None
        except ApprovalError:
            return False
    
    async def approve_tool_with_etdi(
        self, 
        tool: ETDIToolDefinition, 
        approved_permissions: Optional[List[Permission]] = None
    ) -> ToolApprovalRecord:
        """
        Create and store an approval record for an ETDI tool
        
        Args:
            tool: Tool definition to approve
            approved_permissions: Specific permissions approved (defaults to all tool permissions)
            
        Returns:
            Created approval record
            
        Raises:
            ApprovalError: If approval creation fails
        """
        try:
            # Use provided permissions or all tool permissions
            permissions = approved_permissions or tool.permissions
            
            # Get provider ID from OAuth info
            provider_id = "unknown"
            if tool.security and tool.security.oauth:
                provider_id = tool.security.oauth.provider
            
            # Create definition hash for integrity checking
            definition_hash = self._calculate_definition_hash(tool)
            
            # Create approval record
            record = ToolApprovalRecord(
                tool_id=tool.id,
                provider_id=provider_id,
                approved_version=tool.version,
                permissions=permissions,
                approval_date=datetime.now(),
                definition_hash=definition_hash
            )
            
            # Store the record
            await self.store_approval(record)
            
            logger.info(f"Approved tool {tool.id} v{tool.version} with {len(permissions)} permissions")
            return record
            
        except Exception as e:
            if isinstance(e, ApprovalError):
                raise
            raise ApprovalError(
                f"Failed to approve tool {tool.id}: {e}",
                tool_id=tool.id,
                operation="approve"
            )
    
    async def check_for_changes(self, tool: ETDIToolDefinition) -> Dict[str, Any]:
        """
        Check if a tool has changed since approval
        
        Args:
            tool: Current tool definition
            
        Returns:
            Dictionary with change detection results
        """
        try:
            approval = await self.get_approval(tool.id)
            if not approval:
                return {
                    "has_approval": False,
                    "changes_detected": False,
                    "changes": []
                }
            
            changes = []
            
            # Check version changes
            if tool.version != approval.approved_version:
                changes.append(f"Version changed from {approval.approved_version} to {tool.version}")
            
            # Check provider changes
            current_provider = tool.security.oauth.provider if tool.security and tool.security.oauth else "unknown"
            if current_provider != approval.provider_id:
                changes.append(f"Provider changed from {approval.provider_id} to {current_provider}")
            
            # Check permission changes
            current_scopes = {p.scope for p in tool.permissions}
            approved_scopes = {p.scope for p in approval.permissions}
            
            new_scopes = current_scopes - approved_scopes
            removed_scopes = approved_scopes - current_scopes
            
            if new_scopes:
                changes.append(f"New permissions added: {', '.join(new_scopes)}")
            if removed_scopes:
                changes.append(f"Permissions removed: {', '.join(removed_scopes)}")
            
            # Check definition hash
            current_hash = self._calculate_definition_hash(tool)
            if approval.definition_hash and current_hash != approval.definition_hash:
                changes.append("Tool definition has been modified")
            
            return {
                "has_approval": True,
                "changes_detected": len(changes) > 0,
                "changes": changes,
                "approval_date": approval.approval_date,
                "approved_version": approval.approved_version
            }
            
        except Exception as e:
            logger.error(f"Error checking changes for tool {tool.id}: {e}")
            return {
                "has_approval": False,
                "changes_detected": False,
                "changes": [f"Error checking changes: {str(e)}"],
                "error": str(e)
            }
    
    def _get_approval_filename(self, tool_id: str) -> str:
        """Generate filename for approval record"""
        # Use hash to handle special characters in tool IDs
        safe_id = hashlib.sha256(tool_id.encode()).hexdigest()[:16]
        return f"{safe_id}.approval"
    
    def _calculate_definition_hash(self, tool: ETDIToolDefinition) -> str:
        """Calculate hash of tool definition for integrity checking"""
        # Create a normalized representation for hashing
        hash_data = {
            "id": tool.id,
            "name": tool.name,
            "version": tool.version,
            "description": tool.description,
            "provider": tool.provider,
            "permissions": [p.to_dict() for p in tool.permissions],
            "schema": tool.schema
        }
        
        # Sort keys for consistent hashing
        normalized_json = json.dumps(hash_data, sort_keys=True)
        return hashlib.sha256(normalized_json.encode()).hexdigest()
    
    async def cleanup_expired_approvals(self) -> int:
        """
        Clean up expired approval records
        
        Returns:
            Number of expired approvals removed
        """
        try:
            async with self._lock:
                removed_count = 0
                
                for filepath in self.storage_path.glob("*.approval"):
                    try:
                        with open(filepath, "rb") as f:
                            encrypted_data = f.read()
                        
                        decrypted_data = self.cipher.decrypt(encrypted_data)
                        record_data = json.loads(decrypted_data.decode())
                        record = ToolApprovalRecord.from_dict(record_data)
                        
                        if record.is_expired():
                            filepath.unlink()
                            removed_count += 1
                            logger.debug(f"Removed expired approval: {record.tool_id}")
                            
                    except Exception as e:
                        logger.warning(f"Could not process approval file {filepath}: {e}")
                        continue
                
                if removed_count > 0:
                    logger.info(f"Cleaned up {removed_count} expired approvals")
                
                return removed_count
                
        except Exception as e:
            logger.error(f"Error during approval cleanup: {e}")
            return 0
    
    async def get_storage_stats(self) -> Dict[str, Any]:
        """
        Get storage statistics
        
        Returns:
            Dictionary with storage statistics
        """
        try:
            async with self._lock:
                approval_files = list(self.storage_path.glob("*.approval"))
                total_size = sum(f.stat().st_size for f in approval_files)
                
                return {
                    "storage_path": str(self.storage_path),
                    "total_approvals": len(approval_files),
                    "total_size_bytes": total_size,
                    "encrypted": True
                }
                
        except Exception as e:
            logger.error(f"Error getting storage stats: {e}")
            return {
                "storage_path": str(self.storage_path),
                "error": str(e)
            }