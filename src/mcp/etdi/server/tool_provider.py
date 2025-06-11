"""
Tool Provider SDK for ETDI server-side tool registration and management
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
import json
import hashlib
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding

from ..types import ETDIToolDefinition, SecurityInfo, OAuthInfo, Permission
from ..exceptions import ETDIError, SignatureError, ConfigurationError
from ..oauth import OAuthManager

logger = logging.getLogger(__name__)


class ToolProvider:
    """
    Tool Provider SDK for creating, signing, and registering ETDI tools
    """
    
    def __init__(
        self, 
        provider_id: str,
        provider_name: str,
        private_key: Optional[str] = None,
        oauth_manager: Optional[OAuthManager] = None
    ):
        """
        Initialize tool provider
        
        Args:
            provider_id: Unique provider identifier
            provider_name: Human-readable provider name
            private_key: PEM-encoded private key for signing
            oauth_manager: OAuth manager for token-based signing
        """
        self.provider_id = provider_id
        self.provider_name = provider_name
        self.oauth_manager = oauth_manager
        self._private_key = None
        self._registered_tools: Dict[str, ETDIToolDefinition] = {}
        
        if private_key:
            self._load_private_key(private_key)
        
        # Allow basic operation without security (for demos and development)
        # In production, at least one security method should be used
        if not private_key and not oauth_manager:
            logger.warning("Tool provider created without security (no private key or OAuth manager)")
            logger.warning("This is suitable for development/demo only - use security in production")
    
    def _load_private_key(self, private_key_pem: str) -> None:
        """Load private key from PEM string"""
        try:
            self._private_key = serialization.load_pem_private_key(
                private_key_pem.encode(),
                password=None
            )
        except Exception as e:
            raise ConfigurationError(f"Failed to load private key: {e}")
    
    def _sign_definition(self, tool_definition: ETDIToolDefinition) -> str:
        """Sign tool definition with private key"""
        if not self._private_key:
            raise SignatureError("No private key available for signing")
        
        # Create canonical representation for signing
        canonical_data = {
            "id": tool_definition.id,
            "name": tool_definition.name,
            "version": tool_definition.version,
            "description": tool_definition.description,
            "provider": tool_definition.provider,
            "schema": tool_definition.schema,
            "permissions": [p.to_dict() for p in tool_definition.permissions]
        }
        
        # Convert to deterministic JSON
        canonical_json = json.dumps(canonical_data, sort_keys=True, separators=(',', ':'))
        
        try:
            # Sign the canonical representation
            signature = self._private_key.sign(
                canonical_json.encode(),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            # Return base64-encoded signature
            import base64
            return base64.b64encode(signature).decode()
            
        except Exception as e:
            raise SignatureError(f"Failed to sign tool definition: {e}")
    
    async def _get_oauth_token(self, tool_definition: ETDIToolDefinition) -> str:
        """Get OAuth token for tool definition"""
        if not self.oauth_manager:
            raise ConfigurationError("OAuth manager not configured")
        
        # Get permission scopes
        scopes = tool_definition.get_permission_scopes()
        
        # Get the first available provider
        providers = self.oauth_manager.list_providers()
        if not providers:
            raise ConfigurationError("No OAuth providers available")
        
        provider_name = providers[0]  # Use first available provider
        
        # Get token from OAuth manager
        token = await self.oauth_manager.get_token(
            provider_name,
            tool_definition.id,
            scopes
        )
        
        return token
    
    async def register_tool(
        self, 
        tool_id: str,
        name: str,
        version: str,
        description: str,
        schema: Dict[str, Any],
        permissions: List[Permission],
        use_oauth: bool = True
    ) -> ETDIToolDefinition:
        """
        Register a new tool with ETDI security
        
        Args:
            tool_id: Unique tool identifier
            name: Human-readable tool name
            version: Semantic version
            description: Tool description
            schema: JSON schema for tool parameters
            permissions: Required permissions
            use_oauth: Whether to use OAuth tokens
            
        Returns:
            Signed tool definition
        """
        try:
            # Create tool definition
            tool_definition = ETDIToolDefinition(
                id=tool_id,
                name=name,
                version=version,
                description=description,
                provider={
                    "id": self.provider_id,
                    "name": self.provider_name
                },
                schema=schema,
                permissions=permissions
            )
            
            # Create security info
            security_info = SecurityInfo()
            
            if use_oauth and self.oauth_manager:
                # Get OAuth token
                token = await self._get_oauth_token(tool_definition)
                
                # Determine OAuth provider
                providers = self.oauth_manager.list_providers()
                oauth_provider = providers[0] if providers else "default"
                
                security_info.oauth = OAuthInfo(
                    token=token,
                    provider=oauth_provider,
                    issued_at=datetime.now()
                )
            
            if self._private_key:
                # Sign the definition
                signature = self._sign_definition(tool_definition)
                security_info.signature = signature
                security_info.signature_algorithm = "RS256"
            
            tool_definition.security = security_info
            
            # Store registered tool
            self._registered_tools[tool_id] = tool_definition
            
            logger.info(f"Registered tool {tool_id} with ETDI security")
            return tool_definition
            
        except Exception as e:
            logger.error(f"Failed to register tool {tool_id}: {e}")
            raise ETDIError(f"Tool registration failed: {e}")
    
    async def update_tool(
        self, 
        tool_id: str,
        version: str,
        description: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
        permissions: Optional[List[Permission]] = None
    ) -> ETDIToolDefinition:
        """
        Update an existing tool (creates new version)
        
        Args:
            tool_id: Tool identifier
            version: New version
            description: Updated description
            schema: Updated schema
            permissions: Updated permissions
            
        Returns:
            Updated signed tool definition
        """
        if tool_id not in self._registered_tools:
            raise ETDIError(f"Tool {tool_id} not found")
        
        current_tool = self._registered_tools[tool_id]
        
        # Create updated tool definition
        updated_tool = ETDIToolDefinition(
            id=tool_id,
            name=current_tool.name,
            version=version,
            description=description or current_tool.description,
            provider=current_tool.provider,
            schema=schema or current_tool.schema,
            permissions=permissions or current_tool.permissions
        )
        
        # Re-sign the updated definition
        security_info = SecurityInfo()
        
        if self.oauth_manager:
            try:
                token = await self._get_oauth_token(updated_tool)
                providers = self.oauth_manager.list_providers()
                oauth_provider = providers[0] if providers else "default"
                
                security_info.oauth = OAuthInfo(
                    token=token,
                    provider=oauth_provider,
                    issued_at=datetime.now()
                )
            except Exception as e:
                logger.warning(f"Failed to get OAuth token for updated tool {tool_id}: {e}")
        
        if self._private_key:
            signature = self._sign_definition(updated_tool)
            security_info.signature = signature
            security_info.signature_algorithm = "RS256"
        
        updated_tool.security = security_info
        
        # Update stored tool
        self._registered_tools[tool_id] = updated_tool
        
        logger.info(f"Updated tool {tool_id} to version {version}")
        return updated_tool
    
    def get_tool(self, tool_id: str) -> Optional[ETDIToolDefinition]:
        """Get a registered tool by ID"""
        return self._registered_tools.get(tool_id)
    
    def get_all_tools(self) -> List[ETDIToolDefinition]:
        """Get all registered tools"""
        return list(self._registered_tools.values())
    
    def remove_tool(self, tool_id: str) -> bool:
        """Remove a tool from registration"""
        if tool_id in self._registered_tools:
            del self._registered_tools[tool_id]
            logger.info(f"Removed tool {tool_id}")
            return True
        return False
    
    def get_tool_definition_hash(self, tool_id: str) -> Optional[str]:
        """Get hash of tool definition for integrity checking"""
        tool = self.get_tool(tool_id)
        if not tool:
            return None
        
        # Create canonical representation
        canonical_data = {
            "id": tool.id,
            "name": tool.name,
            "version": tool.version,
            "description": tool.description,
            "provider": tool.provider,
            "schema": tool.schema,
            "permissions": [p.to_dict() for p in tool.permissions]
        }
        
        canonical_json = json.dumps(canonical_data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical_json.encode()).hexdigest()
    
    async def refresh_tool_tokens(self, tool_ids: Optional[List[str]] = None) -> Dict[str, bool]:
        """
        Refresh OAuth tokens for tools
        
        Args:
            tool_ids: Specific tools to refresh (all if None)
            
        Returns:
            Dictionary mapping tool IDs to refresh success status
        """
        if not self.oauth_manager:
            return {}
        
        tools_to_refresh = tool_ids or list(self._registered_tools.keys())
        results = {}
        
        for tool_id in tools_to_refresh:
            try:
                tool = self._registered_tools.get(tool_id)
                if not tool or not tool.security or not tool.security.oauth:
                    results[tool_id] = False
                    continue
                
                # Get new token
                new_token = await self._get_oauth_token(tool)
                
                # Update tool's OAuth info
                tool.security.oauth.token = new_token
                tool.security.oauth.issued_at = datetime.now()
                
                results[tool_id] = True
                logger.info(f"Refreshed token for tool {tool_id}")
                
            except Exception as e:
                logger.error(f"Failed to refresh token for tool {tool_id}: {e}")
                results[tool_id] = False
        
        return results
    
    def get_provider_stats(self) -> Dict[str, Any]:
        """Get provider statistics"""
        tools = list(self._registered_tools.values())
        
        oauth_tools = sum(1 for t in tools if t.security and t.security.oauth)
        signed_tools = sum(1 for t in tools if t.security and t.security.signature)
        
        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "total_tools": len(tools),
            "oauth_enabled_tools": oauth_tools,
            "cryptographically_signed_tools": signed_tools,
            "has_private_key": self._private_key is not None,
            "has_oauth_manager": self.oauth_manager is not None
        }