"""
ETDI-enhanced MCP client session with security verification
"""

import logging
from typing import Any, Dict, List, Optional
from mcp.client.session import ClientSession
from mcp.types import Tool, CallToolRequest, CallToolResult

from ..types import ETDIToolDefinition, VerificationStatus
from ..exceptions import ETDIError, PermissionError
from .verifier import ETDIVerifier
from .approval_manager import ApprovalManager

logger = logging.getLogger(__name__)


class ETDISecureClientSession(ClientSession):
    """
    Enhanced MCP client session with ETDI security verification
    """
    
    def __init__(
        self,
        verifier: ETDIVerifier,
        approval_manager: ApprovalManager,
        request_signer: Optional[Any] = None,
        security_level: Optional[Any] = None,
        **kwargs
    ):
        """
        Initialize secure client session
        
        Args:
            verifier: ETDI tool verifier
            approval_manager: Tool approval manager
            request_signer: Request signer for cryptographic signing
            security_level: Security level (BASIC, ENHANCED, STRICT)
            **kwargs: Additional arguments for base ClientSession
        """
        super().__init__(**kwargs)
        self.verifier = verifier
        self.approval_manager = approval_manager
        self.request_signer = request_signer
        self.security_level = security_level
        self._etdi_tools: Dict[str, ETDIToolDefinition] = {}
    
    async def list_tools(self) -> List[ETDIToolDefinition]:
        """
        List tools with ETDI security verification
        
        Returns:
            List of verified ETDI tool definitions
        """
        try:
            # Get standard MCP tools
            standard_tools = await super().list_tools()
            
            # Convert to ETDI tools and verify
            etdi_tools = []
            for tool in standard_tools.tools:
                etdi_tool = self._convert_to_etdi_tool(tool)
                
                # Verify the tool
                verification_result = await self.verifier.verify_tool(etdi_tool)
                if verification_result.valid:
                    etdi_tool.verification_status = VerificationStatus.VERIFIED
                else:
                    etdi_tool.verification_status = VerificationStatus.TOKEN_INVALID
                
                etdi_tools.append(etdi_tool)
                self._etdi_tools[etdi_tool.id] = etdi_tool
            
            logger.info(f"Listed {len(etdi_tools)} tools, {sum(1 for t in etdi_tools if t.verification_status == VerificationStatus.VERIFIED)} verified")
            return etdi_tools
            
        except Exception as e:
            logger.error(f"Error listing tools: {e}")
            raise ETDIError(f"Tool listing failed: {e}")
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """
        Call a tool with ETDI security checks
        
        Args:
            name: Tool name
            arguments: Tool arguments
            
        Returns:
            Tool execution result
            
        Raises:
            ETDIError: If security checks fail
            PermissionError: If tool lacks required permissions
        """
        try:
            # Get tool definition
            etdi_tool = self._etdi_tools.get(name)
            if not etdi_tool:
                # Try to refresh tool list
                await self.list_tools()
                etdi_tool = self._etdi_tools.get(name)
                
                if not etdi_tool:
                    raise ETDIError(f"Tool not found: {name}")
            
            # Check if tool is approved
            approval = await self.approval_manager.get_approval(etdi_tool.id)
            
            # Perform pre-invocation security check
            check_result = await self.verifier.check_tool_before_invocation(
                etdi_tool,
                approval.to_dict() if approval else None
            )
            
            if not check_result.can_proceed:
                if check_result.requires_reapproval:
                    raise PermissionError(
                        f"Tool {name} requires re-approval: {check_result.reason}",
                        tool_id=name
                    )
                else:
                    raise ETDIError(f"Tool {name} cannot be invoked: {check_result.reason}")
            
            # Check if tool requires request signing and we're in STRICT mode
            requires_signing = (
                hasattr(etdi_tool, 'require_request_signing') and
                etdi_tool.require_request_signing and
                self.request_signer is not None
            )
            
            if requires_signing:
                # Import SecurityLevel here to avoid circular imports
                try:
                    from ..types import SecurityLevel
                    
                    if self.security_level == SecurityLevel.STRICT:
                        # Sign the request using ETDI protocol extension
                        signature_headers = self.request_signer.sign_tool_invocation(name, arguments)
                        
                        # Create signed MCP request
                        from ..types_extensions import create_signed_call_tool_request
                        signed_request = create_signed_call_tool_request(
                            name=name,
                            arguments=arguments,
                            signature_headers=signature_headers
                        )
                        
                        # Call the tool using signed request
                        result = await super().call_tool(signed_request)
                        
                        logger.debug(f"Signed request for tool {name} in STRICT mode")
                    else:
                        # Warn but don't block in non-STRICT modes
                        logger.warning(
                            f"Tool {name} requires request signing but session is not in STRICT mode. "
                            "Request signing is only enforced in STRICT mode for backward compatibility."
                        )
                        # Call without signing
                        request = CallToolRequest(name=name, arguments=arguments)
                        result = await super().call_tool(request)
                except ImportError:
                    logger.warning("SecurityLevel not available, skipping request signing")
                    # Call without signing
                    request = CallToolRequest(name=name, arguments=arguments)
                    result = await super().call_tool(request)
            else:
                # Call the tool using standard MCP
                request = CallToolRequest(name=name, arguments=arguments)
                result = await super().call_tool(request)
            
            logger.info(f"Successfully called tool {name}")
            return result
            
        except Exception as e:
            logger.error(f"Error calling tool {name}: {e}")
            if isinstance(e, (ETDIError, PermissionError)):
                raise
            raise ETDIError(f"Tool invocation failed: {e}")
    
    def _convert_to_etdi_tool(self, tool: Tool) -> ETDIToolDefinition:
        """
        Convert standard MCP tool to ETDI tool definition
        
        Args:
            tool: Standard MCP tool
            
        Returns:
            ETDI tool definition
        """
        # Extract ETDI security information if present
        security_info = None
        if hasattr(tool, 'security') and tool.security:
            from ..types import SecurityInfo, OAuthInfo
            oauth_data = getattr(tool.security, 'oauth', None)
            if oauth_data:
                security_info = SecurityInfo(
                    oauth=OAuthInfo(
                        token=getattr(oauth_data, 'token', ''),
                        provider=getattr(oauth_data, 'provider', '')
                    )
                )
        
        # Extract permissions if present
        permissions = []
        if hasattr(tool, 'permissions') and tool.permissions:
            from ..types import Permission
            for perm in tool.permissions:
                permissions.append(Permission(
                    name=getattr(perm, 'name', ''),
                    description=getattr(perm, 'description', ''),
                    scope=getattr(perm, 'scope', ''),
                    required=getattr(perm, 'required', True)
                ))
        
        # Extract provider information
        provider_info = {"id": "unknown", "name": "Unknown Provider"}
        if hasattr(tool, 'provider') and tool.provider:
            provider_info = {
                "id": getattr(tool.provider, 'id', 'unknown'),
                "name": getattr(tool.provider, 'name', 'Unknown Provider')
            }
        
        return ETDIToolDefinition(
            id=tool.name,  # MCP uses name as identifier
            name=tool.name,
            version=getattr(tool, 'version', '1.0.0'),
            description=tool.description or '',
            provider=provider_info,
            schema=tool.inputSchema or {},
            permissions=permissions,
            security=security_info,
            verification_status=VerificationStatus.UNVERIFIED
        )
    
    async def approve_tool(self, tool_name: str) -> None:
        """
        Approve a tool for usage
        
        Args:
            tool_name: Name of tool to approve
        """
        etdi_tool = self._etdi_tools.get(tool_name)
        if not etdi_tool:
            raise ETDIError(f"Tool not found: {tool_name}")
        
        await self.approval_manager.approve_tool_with_etdi(etdi_tool)
        logger.info(f"Approved tool: {tool_name}")
    
    async def get_tool_security_status(self, tool_name: str) -> Dict[str, Any]:
        """
        Get security status for a tool
        
        Args:
            tool_name: Name of tool
            
        Returns:
            Security status information
        """
        etdi_tool = self._etdi_tools.get(tool_name)
        if not etdi_tool:
            return {"error": "Tool not found"}
        
        approval = await self.approval_manager.get_approval(etdi_tool.id)
        changes = await self.approval_manager.check_for_changes(etdi_tool)
        
        return {
            "tool_id": etdi_tool.id,
            "verification_status": etdi_tool.verification_status.value,
            "has_oauth": etdi_tool.security and etdi_tool.security.oauth is not None,
            "is_approved": approval is not None,
            "approval_date": approval.approval_date.isoformat() if approval else None,
            "changes_detected": changes.get("changes_detected", False),
            "changes": changes.get("changes", [])
        }
    
    async def _inject_signature_headers(self, signature_headers: Dict[str, str]) -> None:
        """
        Inject signature headers into the MCP session transport
        
        Args:
            signature_headers: Headers to inject
        """
        try:
            # Check if transport is ETDI-enhanced
            if hasattr(self, '_transport') and hasattr(self._transport, 'add_signature_headers'):
                # Use ETDI transport wrapper
                self._transport.add_signature_headers(signature_headers)
                logger.debug("Injected signature headers using ETDI transport wrapper")
                return
            
            # Fallback to manual injection for non-ETDI transports
            if hasattr(self, '_transport'):
                transport = self._transport
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
                if not hasattr(self, '_etdi_signature_headers'):
                    self._etdi_signature_headers = {}
                self._etdi_signature_headers.update(signature_headers)
                logger.debug("Stored signature headers on session object")
                
        except Exception as e:
            logger.error(f"Failed to inject signature headers: {e}")
            # Don't raise - signing is best effort for compatibility