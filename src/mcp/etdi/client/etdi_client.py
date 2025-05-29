"""
Main ETDI client for secure tool discovery and invocation
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union, Callable
from datetime import datetime

from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

from ..types import (
    ETDIToolDefinition,
    ETDIClientConfig,
    OAuthConfig,
    SecurityLevel,
    VerificationStatus,
    Permission,
    SecurityInfo,
    OAuthInfo
)
from ..exceptions import ETDIError, ConfigurationError, ToolNotFoundError
from ..oauth import OAuthManager, Auth0Provider, OktaProvider, AzureADProvider
from ..oauth.custom import CustomOAuthProvider, GenericOAuthProvider
from .verifier import ETDIVerifier
from .approval_manager import ApprovalManager
from ..events import EventType, emit_tool_event, emit_security_event, get_event_emitter

logger = logging.getLogger(__name__)


class ETDIClient:
    """
    Main ETDI client for secure tool operations with MCP integration
    """
    
    def __init__(self, config: Union[ETDIClientConfig, Dict[str, Any]]):
        """
        Initialize ETDI client
        
        Args:
            config: ETDI client configuration
        """
        if isinstance(config, dict):
            self.config = ETDIClientConfig(**config)
        else:
            self.config = config
        
        # Initialize components
        self.oauth_manager = OAuthManager()
        self.verifier: Optional[ETDIVerifier] = None
        self.approval_manager: Optional[ApprovalManager] = None
        self._initialized = False
        
        # MCP integration
        self._mcp_sessions: Dict[str, ClientSession] = {}
        self._discovered_tools: Dict[str, ETDIToolDefinition] = {}
        
        # Request signing components
        self._request_signer = None
        self._key_exchange_manager = None
        
        # Event system integration
        self.event_emitter = get_event_emitter()
        
        # Event callbacks (legacy support)
        self._event_callbacks: Dict[str, List[callable]] = {}
    
    async def initialize(self) -> None:
        """Initialize the ETDI client"""
        if self._initialized:
            return
        
        try:
            # Initialize OAuth providers
            await self._setup_oauth_providers()
            
            # Initialize verifier
            self.verifier = ETDIVerifier(
                self.oauth_manager,
                cache_ttl=self.config.verification_cache_ttl
            )
            
            # Initialize approval manager
            storage_config = self.config.storage_config or {}
            self.approval_manager = ApprovalManager(
                storage_path=storage_config.get("path"),
                encryption_key=storage_config.get("encryption_key")
            )
            
            # Initialize request signing if enabled
            if self.config.enable_request_signing or self.config.security_level == SecurityLevel.STRICT:
                await self._initialize_request_signing()
            
            # Initialize OAuth manager
            await self.oauth_manager.initialize_all()
            
            self._initialized = True
            
            # Emit initialization event
            emit_tool_event(
                EventType.CLIENT_INITIALIZED,
                "etdi_client",
                "ETDIClient",
                data={"security_level": self.config.security_level.value if hasattr(self.config.security_level, 'value') else str(self.config.security_level)}
            )
            
            logger.info("ETDI client initialized successfully")
            
        except Exception as e:
            raise ETDIError(f"Failed to initialize ETDI client: {e}")
    
    async def cleanup(self) -> None:
        """Cleanup resources"""
        # Close MCP sessions
        for session in self._mcp_sessions.values():
            try:
                await session.close()
            except Exception as e:
                logger.warning(f"Error closing MCP session: {e}")
        
        self._mcp_sessions.clear()
        
        if self.oauth_manager:
            await self.oauth_manager.cleanup_all()
        
        # Emit disconnection event
        emit_tool_event(
            EventType.CLIENT_DISCONNECTED,
            "etdi_client",
            "ETDIClient"
        )
        
        self._initialized = False
    
    async def connect_to_server(self, server_command: List[str], server_name: Optional[str] = None) -> str:
        """
        Connect to an MCP server
        
        Args:
            server_command: Command to start the MCP server
            server_name: Optional name for the server
            
        Returns:
            Server identifier
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Create session
            session = await stdio_client(server_command)
            
            # Generate server ID
            server_id = server_name or f"server_{len(self._mcp_sessions)}"
            self._mcp_sessions[server_id] = session
            
            # Emit connection event
            emit_tool_event(
                EventType.CLIENT_CONNECTED,
                server_id,
                "ETDIClient",
                data={"server_command": server_command}
            )
            
            logger.info(f"Connected to MCP server: {server_id}")
            return server_id
            
        except Exception as e:
            logger.error(f"Failed to connect to MCP server: {e}")
            raise ETDIError(f"Server connection failed: {e}")
    
    async def __aenter__(self):
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
    
    async def discover_tools(self, server_ids: Optional[List[str]] = None) -> List[ETDIToolDefinition]:
        """
        Discover available tools from MCP servers
        
        Args:
            server_ids: List of server IDs to discover from (all if None)
            
        Returns:
            List of discovered ETDI tool definitions
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            discovered_tools = []
            servers_to_query = server_ids or list(self._mcp_sessions.keys())
            
            for server_id in servers_to_query:
                if server_id not in self._mcp_sessions:
                    logger.warning(f"Server {server_id} not found, skipping")
                    continue
                
                session = self._mcp_sessions[server_id]
                
                try:
                    # Get tools from MCP server
                    tools_response = await session.list_tools()
                    
                    for mcp_tool in tools_response.tools:
                        # Convert MCP tool to ETDI tool definition
                        etdi_tool = self._convert_mcp_tool_to_etdi(mcp_tool, server_id)
                        discovered_tools.append(etdi_tool)
                        
                        # Store in cache
                        self._discovered_tools[etdi_tool.id] = etdi_tool
                        
                        # Emit discovery event
                        emit_tool_event(
                            EventType.TOOL_DISCOVERED,
                            etdi_tool.id,
                            "ETDIClient",
                            tool_name=etdi_tool.name,
                            tool_version=etdi_tool.version,
                            provider_id=etdi_tool.provider.get("id"),
                            data={"server_id": server_id}
                        )
                
                except Exception as e:
                    logger.error(f"Error discovering tools from server {server_id}: {e}")
                    continue
            
            # Filter tools based on security level
            if self.config.security_level == SecurityLevel.STRICT:
                # Only return verified tools
                verified_tools = []
                for tool in discovered_tools:
                    if await self.verify_tool(tool):
                        verified_tools.append(tool)
                return verified_tools
            elif self.config.security_level == SecurityLevel.ENHANCED:
                # Return all tools but mark verification status
                for tool in discovered_tools:
                    await self.verify_tool(tool)
                return discovered_tools
            else:
                # Basic level - return all tools
                return discovered_tools
            
        except Exception as e:
            logger.error(f"Error discovering tools: {e}")
            raise ETDIError(f"Tool discovery failed: {e}")
    
    def _convert_mcp_tool_to_etdi(self, mcp_tool: Any, server_id: str) -> ETDIToolDefinition:
        """
        Convert MCP tool definition to ETDI tool definition
        
        Args:
            mcp_tool: MCP tool definition
            server_id: Server identifier
            
        Returns:
            ETDI tool definition
        """
        # Extract basic information
        tool_id = mcp_tool.name
        name = getattr(mcp_tool, 'displayName', mcp_tool.name)
        description = getattr(mcp_tool, 'description', '')
        
        # Create provider information
        provider = {
            "id": server_id,
            "name": f"MCP Server {server_id}"
        }
        
        # Convert schema
        schema = getattr(mcp_tool, 'inputSchema', {"type": "object"})
        
        # Create basic permissions (MCP tools don't have explicit permissions)
        permissions = [
            Permission(
                name="execute",
                description=f"Execute {name}",
                scope=f"tool:{tool_id}:execute",
                required=True
            )
        ]
        
        # Create ETDI tool definition
        etdi_tool = ETDIToolDefinition(
            id=tool_id,
            name=name,
            version="1.0.0",  # MCP tools don't have versions
            description=description,
            provider=provider,
            schema=schema,
            permissions=permissions
        )
        
        return etdi_tool
    
    async def verify_tool(self, tool: ETDIToolDefinition) -> bool:
        """
        Verify a tool's security credentials
        
        Args:
            tool: Tool to verify
            
        Returns:
            True if tool is verified
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            result = await self.verifier.verify_tool(tool)
            
            if result.valid:
                emit_tool_event(
                    EventType.TOOL_VERIFIED,
                    tool.id,
                    "ETDIClient",
                    tool_name=tool.name,
                    tool_version=tool.version,
                    provider_id=tool.provider.get("id")
                )
                self._emit_event("tool_verified", {"tool": tool})
            else:
                emit_security_event(
                    EventType.SIGNATURE_FAILED,
                    "ETDIClient",
                    "medium",
                    threat_type="verification_failure",
                    details={"tool_id": tool.id, "error": result.error}
                )
                self._emit_event("tool_verification_failed", {
                    "tool": tool,
                    "error": result.error
                })
            
            return result.valid
            
        except Exception as e:
            logger.error(f"Error verifying tool {tool.id}: {e}")
            return False
    
    async def approve_tool(self, tool: ETDIToolDefinition, permissions: Optional[List[Permission]] = None) -> None:
        """
        Approve a tool for usage
        
        Args:
            tool: Tool to approve
            permissions: Specific permissions to approve (defaults to all tool permissions)
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Verify tool before approval
            if not await self.verify_tool(tool):
                raise ETDIError(f"Cannot approve unverified tool: {tool.id}")
            
            # Create approval record
            await self.approval_manager.approve_tool_with_etdi(tool, permissions)
            
            # Emit approval event
            emit_tool_event(
                EventType.TOOL_APPROVED,
                tool.id,
                "ETDIClient",
                tool_name=tool.name,
                tool_version=tool.version,
                provider_id=tool.provider.get("id")
            )
            
            self._emit_event("tool_approved", {"tool": tool, "permissions": permissions})
            logger.info(f"Tool {tool.id} approved successfully")
            
        except Exception as e:
            logger.error(f"Error approving tool {tool.id}: {e}")
            raise ETDIError(f"Tool approval failed: {e}")
    
    async def is_tool_approved(self, tool_id: str) -> bool:
        """
        Check if a tool is approved
        
        Args:
            tool_id: Tool identifier
            
        Returns:
            True if tool is approved
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            return await self.approval_manager.is_tool_approved(tool_id)
        except Exception as e:
            logger.error(f"Error checking approval for tool {tool_id}: {e}")
            return False
    
    async def invoke_tool(self, tool_id: str, params: Any) -> Any:
        """
        Invoke a tool with parameters
        
        Args:
            tool_id: Tool identifier
            params: Tool parameters
            
        Returns:
            Tool execution result
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Get tool definition
            tool = self._discovered_tools.get(tool_id)
            if not tool:
                raise ToolNotFoundError(f"Tool {tool_id} not found", tool_id=tool_id)
            
            # Check if tool is approved
            if not await self.is_tool_approved(tool_id):
                raise ETDIError(f"Tool {tool_id} is not approved")
            
            # Check tool before invocation
            stored_approval = await self.approval_manager.get_approval_record(tool_id)
            check_result = await self.verifier.check_tool_before_invocation(tool, stored_approval)
            
            if not check_result.can_proceed:
                if check_result.requires_reapproval:
                    emit_security_event(
                        EventType.VERSION_CHANGED,
                        "ETDIClient",
                        "high",
                        threat_type="version_change",
                        details={"tool_id": tool_id, "changes": check_result.changes_detected}
                    )
                    raise ETDIError(f"Tool {tool_id} requires re-approval: {check_result.reason}")
                else:
                    emit_security_event(
                        EventType.SECURITY_VIOLATION,
                        "ETDIClient",
                        "high",
                        threat_type="invocation_blocked",
                        details={"tool_id": tool_id, "reason": check_result.reason}
                    )
                    raise ETDIError(f"Tool {tool_id} invocation blocked: {check_result.reason}")
            
            # Find the server that hosts this tool
            server_id = tool.provider.get("id")
            if server_id not in self._mcp_sessions:
                raise ETDIError(f"Server {server_id} not connected")
            
            session = self._mcp_sessions[server_id]
            
            # Sign request if tool requires it and create enhanced request
            if tool.require_request_signing and self._request_signer:
                # Create signature headers for the tool invocation
                signature_headers = self._request_signer.sign_tool_invocation(tool_id, params)
                
                # Create signed MCP request using ETDI protocol extension
                from ..types_extensions import create_signed_call_tool_request
                signed_request = create_signed_call_tool_request(
                    name=tool_id,
                    arguments=params,
                    signature_headers=signature_headers
                )
                
                # Invoke tool via MCP with signed request
                result = await session.call_tool(signed_request)
                
                logger.debug(f"Signed request for tool {tool_id} requiring request signing")
            else:
                # Invoke tool via MCP without signing
                result = await session.call_tool(tool_id, params)
            
            # Emit invocation event
            emit_tool_event(
                EventType.TOOL_INVOKED,
                tool_id,
                "ETDIClient",
                tool_name=tool.name,
                tool_version=tool.version,
                provider_id=tool.provider.get("id"),
                data={"parameters": params}
            )
            
            self._emit_event("tool_invoked", {"tool_id": tool_id, "params": params})
            
            return result.content[0].text if result.content else "No result"
            
        except Exception as e:
            logger.error(f"Error invoking tool {tool_id}: {e}")
            if isinstance(e, ETDIError):
                raise
            raise ETDIError(f"Tool invocation failed: {e}")
    
    async def check_version_change(self, tool_id: str) -> bool:
        """
        Check if a tool's version has changed since approval
        
        Args:
            tool_id: Tool identifier
            
        Returns:
            True if version has changed
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            current_tool = self._discovered_tools.get(tool_id)
            if not current_tool:
                return False
            
            stored_approval = await self.approval_manager.get_approval_record(tool_id)
            if not stored_approval:
                return False
            
            return current_tool.version != stored_approval.approved_version
            
        except Exception as e:
            logger.error(f"Error checking version change for tool {tool_id}: {e}")
            return False
    
    async def request_reapproval(self, tool_id: str) -> None:
        """
        Request re-approval for a tool
        
        Args:
            tool_id: Tool identifier
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            tool = self._discovered_tools.get(tool_id)
            if not tool:
                raise ToolNotFoundError(f"Tool {tool_id} not found", tool_id=tool_id)
            
            # Remove existing approval
            await self.approval_manager.revoke_approval(tool_id)
            
            # Emit reapproval request event
            emit_tool_event(
                EventType.TOOL_REAPPROVAL_REQUESTED,
                tool_id,
                "ETDIClient",
                tool_name=tool.name,
                tool_version=tool.version,
                provider_id=tool.provider.get("id")
            )
            
            self._emit_event("tool_reapproval_requested", {"tool_id": tool_id})
            logger.info(f"Re-approval requested for tool {tool_id}")
            
        except Exception as e:
            logger.error(f"Error requesting re-approval for tool {tool_id}: {e}")
            raise ETDIError(f"Re-approval request failed: {e}")
    
    async def check_permission(self, tool_id: str, permission: str) -> bool:
        """
        Check if a tool has a specific permission
        
        Args:
            tool_id: Tool identifier
            permission: Permission scope to check
            
        Returns:
            True if tool has the permission
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            tool = self._discovered_tools.get(tool_id)
            if not tool:
                return False
            
            # Check if tool has the permission
            for perm in tool.permissions:
                if perm.scope == permission:
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking permission {permission} for tool {tool_id}: {e}")
            return False
    
    def on(self, event: str, listener: Callable) -> 'ETDIClient':
        """
        Register an event listener
        
        Args:
            event: Event name
            listener: Callback function
            
        Returns:
            Self for chaining
        """
        if event not in self._event_listeners:
            self._event_listeners[event] = []
        self._event_listeners[event].append(listener)
        return self
    
    def off(self, event: str, listener: Callable) -> 'ETDIClient':
        """
        Remove an event listener
        
        Args:
            event: Event name
            listener: Callback function to remove
            
        Returns:
            Self for chaining
        """
        if event in self._event_listeners:
            try:
                self._event_listeners[event].remove(listener)
            except ValueError:
                pass  # Listener not found
        return self
    
    async def request_reapproval(self, tool_id: str) -> None:
        """
        Request re-approval for a tool
        
        Args:
            tool_id: Tool identifier
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            # Remove existing approval to force re-approval
            await self.approval_manager.remove_approval(tool_id)
            
            self._emit_event("reapproval_requested", {"tool_id": tool_id})
            logger.info(f"Re-approval requested for tool {tool_id}")
            
        except Exception as e:
            logger.error(f"Error requesting re-approval for tool {tool_id}: {e}")
            raise ETDIError(f"Re-approval request failed: {e}")
    
    async def check_permission(self, tool_id: str, permission: str) -> bool:
        """
        Check if a tool has a specific permission
        
        Args:
            tool_id: Tool identifier
            permission: Permission to check
            
        Returns:
            True if tool has the permission
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            approval = await self.approval_manager.get_approval(tool_id)
            if not approval:
                return False
            
            return any(p.scope == permission for p in approval.permissions)
            
        except Exception as e:
            logger.error(f"Error checking permission {permission} for tool {tool_id}: {e}")
            return False
    
    def on(self, event: str, callback: callable) -> None:
        """
        Register event callback
        
        Args:
            event: Event name
            callback: Callback function
        """
        if event not in self._event_callbacks:
            self._event_callbacks[event] = []
        self._event_callbacks[event].append(callback)
    
    def off(self, event: str, callback: callable) -> None:
        """
        Remove event callback
        
        Args:
            event: Event name
            callback: Callback function to remove
        """
        if event in self._event_callbacks:
            try:
                self._event_callbacks[event].remove(callback)
            except ValueError:
                pass
    
    def _emit_event(self, event: str, data: Dict[str, Any]) -> None:
        """Emit event to registered callbacks"""
        if event in self._event_callbacks:
            for callback in self._event_callbacks[event]:
                try:
                    callback(data)
                except Exception as e:
                    logger.error(f"Error in event callback for {event}: {e}")
    
    async def _initialize_request_signing(self) -> None:
        """Initialize request signing components"""
        try:
            from ..crypto import KeyManager, RequestSigner, KeyExchangeManager
            
            # Initialize key manager
            key_config = self.config.key_config or {}
            key_store_path = key_config.get("private_key_path") or "~/.etdi/keys/client"
            
            key_manager = KeyManager(key_store_path)
            
            # Create or load client key pair
            client_key_id = f"etdi-client-{hash(str(self.config))}"
            key_pair = key_manager.get_or_create_key_pair(client_key_id)
            
            # Initialize request signer
            self._request_signer = RequestSigner(key_manager, client_key_id)
            
            # Initialize key exchange manager
            self._key_exchange_manager = KeyExchangeManager(key_manager, client_key_id)
            
            logger.info("Request signing initialized for ETDI client")
            
        except Exception as e:
            logger.error(f"Failed to initialize request signing: {e}")
            if self.config.security_level == SecurityLevel.STRICT:
                raise ETDIError(f"Request signing required in STRICT mode but initialization failed: {e}")
    
    async def _setup_oauth_providers(self) -> None:
        """Setup OAuth providers from configuration"""
        if not self.config.oauth_config:
            if self.config.security_level in [SecurityLevel.ENHANCED, SecurityLevel.STRICT]:
                raise ConfigurationError("OAuth configuration required for enhanced/strict security levels")
            return
        
        oauth_config = OAuthConfig.from_dict(self.config.oauth_config)
        
        # Create provider based on type
        if oauth_config.provider.lower() == "auth0":
            provider = Auth0Provider(oauth_config)
        elif oauth_config.provider.lower() == "okta":
            provider = OktaProvider(oauth_config)
        elif oauth_config.provider.lower() in ["azure", "azuread", "azure_ad"]:
            provider = AzureADProvider(oauth_config)
        elif oauth_config.provider.lower() == "custom":
            # Custom provider requires endpoints configuration
            endpoints = getattr(oauth_config, 'endpoints', None)
            if not endpoints:
                raise ConfigurationError("Custom OAuth provider requires 'endpoints' configuration")
            provider = GenericOAuthProvider(oauth_config, endpoints)
        else:
            # Try to create a generic provider if endpoints are provided
            endpoints = getattr(oauth_config, 'endpoints', None)
            if endpoints:
                provider = GenericOAuthProvider(oauth_config, endpoints)
            else:
                raise ConfigurationError(f"Unsupported OAuth provider: {oauth_config.provider}. Use 'custom' with endpoints configuration for custom providers.")
        
        self.oauth_manager.register_provider(oauth_config.provider, provider)
    
    def _should_include_tool(self, tool: ETDIToolDefinition) -> bool:
        """Check if tool should be included based on security settings"""
        if tool.verification_status == VerificationStatus.VERIFIED:
            return True
        
        if self.config.security_level == SecurityLevel.STRICT:
            return False
        
        if not self.config.allow_non_etdi_tools and not tool.security:
            return False
        
        return True
    
    async def get_stats(self) -> Dict[str, Any]:
        """
        Get ETDI client statistics
        
        Returns:
            Dictionary with client statistics
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            verification_stats = await self.verifier.get_verification_stats()
            storage_stats = await self.approval_manager.get_storage_stats()
            
            return {
                "initialized": self._initialized,
                "security_level": self.config.security_level.value,
                "oauth_providers": self.oauth_manager.list_providers(),
                "verification": verification_stats,
                "storage": storage_stats,
                "config": {
                    "allow_non_etdi_tools": self.config.allow_non_etdi_tools,
                    "show_unverified_tools": self.config.show_unverified_tools,
                    "verification_cache_ttl": self.config.verification_cache_ttl
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {"error": str(e)}
    
    async def _inject_signature_headers(self, session: Any, signature_headers: Dict[str, str]) -> None:
        """
        Inject signature headers into MCP session transport
        
        Args:
            session: MCP session object
            signature_headers: Headers to inject
        """
        try:
            # Check if transport is ETDI-enhanced
            if hasattr(session, '_transport') and hasattr(session._transport, 'add_signature_headers'):
                # Use ETDI transport wrapper
                session._transport.add_signature_headers(signature_headers)
                logger.debug("Injected signature headers using ETDI transport wrapper")
                return
            
            # Fallback to manual injection for non-ETDI transports
            if hasattr(session, '_transport'):
                transport = session._transport
                transport_type = type(transport).__name__
                
                # Handle different transport types
                if 'SSE' in transport_type or 'HTTP' in transport_type:
                    # For SSE/HTTP transports, add headers to the HTTP client
                    if hasattr(transport, '_client') and hasattr(transport._client, 'headers'):
                        transport._client.headers.update(signature_headers)
                        logger.debug(f"Injected signature headers into {transport_type} transport")
                    elif hasattr(transport, 'headers'):
                        transport.headers.update(signature_headers)
                        logger.debug(f"Injected signature headers into {transport_type} transport")
                
                elif 'WebSocket' in transport_type or 'WS' in transport_type:
                    # For WebSocket transports, store headers for next message
                    if not hasattr(transport, '_etdi_headers'):
                        transport._etdi_headers = {}
                    transport._etdi_headers.update(signature_headers)
                    logger.debug(f"Stored signature headers for {transport_type} transport")
                
                elif 'Stdio' in transport_type:
                    # For stdio transport, embed headers in message envelope
                    if not hasattr(transport, '_etdi_headers'):
                        transport._etdi_headers = {}
                    transport._etdi_headers.update(signature_headers)
                    logger.debug(f"Stored signature headers for {transport_type} transport")
                
                else:
                    logger.warning(f"Unknown transport type {transport_type}, cannot inject signature headers")
            
            # Fallback: store headers on session for custom handling
            else:
                if not hasattr(session, '_etdi_signature_headers'):
                    session._etdi_signature_headers = {}
                session._etdi_signature_headers.update(signature_headers)
                logger.debug("Stored signature headers on session object")
                
        except Exception as e:
            logger.error(f"Failed to inject signature headers: {e}")
            # Don't raise - signing is best effort for compatibility