"""
ETDI extensions to MCP types for request signing support
"""

from typing import Dict, Any, Optional
from mcp.types import CallToolRequestParams, CallToolRequest


class ETDICallToolRequestParams(CallToolRequestParams):
    """Enhanced CallToolRequestParams with ETDI signature support"""
    
    # ETDI signature headers (optional, backward compatible)
    etdi_signature: Optional[str] = None
    etdi_timestamp: Optional[str] = None
    etdi_key_id: Optional[str] = None
    etdi_algorithm: Optional[str] = None
    
    def add_signature_headers(self, headers: Dict[str, str]) -> None:
        """Add ETDI signature headers to the request"""
        if "X-ETDI-Tool-Signature" in headers:
            self.etdi_signature = headers["X-ETDI-Tool-Signature"]
        elif "X-ETDI-Signature" in headers:
            self.etdi_signature = headers["X-ETDI-Signature"]
        if "X-ETDI-Timestamp" in headers:
            self.etdi_timestamp = headers["X-ETDI-Timestamp"]
        if "X-ETDI-Key-ID" in headers:
            self.etdi_key_id = headers["X-ETDI-Key-ID"]
        if "X-ETDI-Algorithm" in headers:
            self.etdi_algorithm = headers["X-ETDI-Algorithm"]
    
    def get_signature_headers(self) -> Dict[str, str]:
        """Extract signature headers from the request"""
        headers = {}
        if self.etdi_signature:
            headers["X-ETDI-Signature"] = self.etdi_signature
        if self.etdi_timestamp:
            headers["X-ETDI-Timestamp"] = self.etdi_timestamp
        if self.etdi_key_id:
            headers["X-ETDI-Key-ID"] = self.etdi_key_id
        if self.etdi_algorithm:
            headers["X-ETDI-Algorithm"] = self.etdi_algorithm
        return headers
    
    def has_signature(self) -> bool:
        """Check if request has ETDI signature"""
        return self.etdi_signature is not None


class ETDICallToolRequest(CallToolRequest):
    """Enhanced CallToolRequest with ETDI signature support"""
    
    params: ETDICallToolRequestParams
    
    def add_signature_headers(self, headers: Dict[str, str]) -> None:
        """Add ETDI signature headers to the request"""
        self.params.add_signature_headers(headers)
    
    def get_signature_headers(self) -> Dict[str, str]:
        """Extract signature headers from the request"""
        return self.params.get_signature_headers()
    
    def has_signature(self) -> bool:
        """Check if request has ETDI signature"""
        return self.params.has_signature()


def enhance_call_tool_request(request: CallToolRequest, signature_headers: Dict[str, str]) -> ETDICallToolRequest:
    """
    Enhance a standard CallToolRequest with ETDI signature headers
    
    Args:
        request: Standard MCP CallToolRequest
        signature_headers: ETDI signature headers to add
        
    Returns:
        Enhanced request with signature headers
    """
    # Create enhanced params
    enhanced_params = ETDICallToolRequestParams(
        name=request.params.name,
        arguments=request.params.arguments
    )
    enhanced_params.add_signature_headers(signature_headers)
    
    # Create enhanced request
    enhanced_request = ETDICallToolRequest(
        method=request.method,
        params=enhanced_params
    )
    
    # Copy any additional fields from original request
    if hasattr(request, 'id'):
        enhanced_request.id = request.id
    if hasattr(request, 'jsonrpc'):
        enhanced_request.jsonrpc = request.jsonrpc
    
    return enhanced_request


def create_signed_call_tool_request(
    name: str, 
    arguments: Optional[Dict[str, Any]] = None,
    signature_headers: Optional[Dict[str, str]] = None
) -> ETDICallToolRequest:
    """
    Create a new CallToolRequest with ETDI signature headers
    
    Args:
        name: Tool name
        arguments: Tool arguments
        signature_headers: ETDI signature headers
        
    Returns:
        Enhanced request with signature headers
    """
    params = ETDICallToolRequestParams(name=name, arguments=arguments)
    
    if signature_headers:
        params.add_signature_headers(signature_headers)
    
    return ETDICallToolRequest(
        method="tools/call",
        params=params
    )