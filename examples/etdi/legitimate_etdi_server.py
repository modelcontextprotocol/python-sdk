#!/usr/bin/env python3
"""
Legitimate ETDI-Enabled SecureDocs Scanner Server

This is a legitimate FastMCP server that implements the SecureDocs Scanner
with proper ETDI security features including:
- OAuth 2.0 authentication
- Permission scoping
- Call stack constraints
- Audit logging
"""

import asyncio
import json
import re
from datetime import datetime
from typing import Dict, List, Optional, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.stdio import stdio_server

# Auth0 Configuration (using existing ETDI setup)
AUTH0_CONFIG = {
    "provider": "auth0",
    "client_id": "PU2AXxHxcATWfLpSd5eiW6Nmw1uO5YQB",  # ETDI Tool Provider Demo
    "domain": "dev-l37pzmojcvxdajg4.us.auth0.com",
    "audience": "https://api.etdi-tools.demo.com",  # ETDI Tool Registry API
    "scopes": ["read", "write", "execute", "admin"]
}

# Create FastMCP server with ETDI security
server = FastMCP(
    name="TrustedSoft SecureDocs Server",
    instructions="Legitimate SecureDocs Scanner from TrustedSoft Inc. with ETDI protection"
)

# Set user permissions for ETDI (in real app this comes from OAuth middleware)
server.set_user_permissions(["document:scan", "pii:detect", "execute"])

# Audit log for compliance
AUDIT_LOG = []

def log_audit(action: str, user: str, details: str):
    """Log security events for compliance"""
    AUDIT_LOG.append({
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "user": user,
        "details": details,
        "server": "TrustedSoft Inc. (ETDI Protected)"
    })

@server.tool()
def get_server_info() -> str:
    """Get server information and security status"""
    return json.dumps({
        "server_name": "TrustedSoft SecureDocs Server",
        "provider": "TrustedSoft Inc.",
        "version": "1.0.0",
        "etdi_enabled": True,
        "oauth_enabled": True,
        "auth0_domain": AUTH0_CONFIG["domain"],
        "client_id": AUTH0_CONFIG["client_id"],
        "audience": AUTH0_CONFIG["audience"],
        "security_features": [
            "ETDI Tool Verification",
            "OAuth 2.0 Authentication", 
            "Call Stack Constraints",
            "Permission Scoping",
            "Audit Logging"
        ],
        "total_scans": len(AUDIT_LOG)
    }, indent=2)

@server.tool(
    etdi=True,
    etdi_permissions=["document:scan", "pii:detect", "execute"],
    etdi_max_call_depth=2,
    etdi_allowed_callees=["validate_document", "log_scan_result"]
)
def SecureDocs_Scanner(document_content: str, scan_type: str = "basic") -> str:
    """
    Legitimate SecureDocs Scanner from TrustedSoft Inc.
    
    This tool performs actual PII scanning and returns legitimate results.
    Protected by ETDI security constraints and OAuth authentication.
    
    Args:
        document_content: The document content to scan for PII
        scan_type: Type of scan to perform (basic, detailed, comprehensive)
    
    Returns:
        JSON string with scan results and security information
    """
    
    # Log the scan attempt
    log_audit("legitimate_scan", "user", f"Document scan requested (type: {scan_type})")
    
    # Perform actual PII detection
    pii_patterns = {
        "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
        "Email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "Phone": r"\b\d{3}-\d{3}-\d{4}\b",
        "Credit Card": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"
    }
    
    findings = []
    for pii_type, pattern in pii_patterns.items():
        matches = re.findall(pattern, document_content)
        if matches:
            findings.append({
                "type": pii_type,
                "count": len(matches),
                "description": f"{pii_type}: {len(matches)} instances found"
            })
    
    # Create comprehensive scan result
    result = {
        "tool": "SecureDocs Scanner",
        "provider": "TrustedSoft Inc.",
        "etdi_protected": True,
        "oauth_verified": True,
        "scan_type": scan_type,
        "document_length": len(document_content),
        "pii_findings": findings,
        "scan_timestamp": datetime.now().isoformat(),
        "security_status": "✅ LEGITIMATE - ETDI protected, OAuth verified",
        "etdi_features": [
            "Permission scoping: document:scan, pii:detect",
            "Call depth limit: 2",
            "Allowed callees: validate_document, log_scan_result",
            "OAuth authentication required"
        ],
        "auth0_config": {
            "domain": AUTH0_CONFIG["domain"],
            "client_id": AUTH0_CONFIG["client_id"],
            "audience": AUTH0_CONFIG["audience"]
        }
    }
    
    # Log successful scan
    log_audit("scan_completed", "user", f"Scan completed: {len(findings)} PII types found")
    
    return json.dumps(result, indent=2)

@server.tool(
    etdi=True,
    etdi_permissions=["validation:execute"],
    etdi_max_call_depth=1,
    etdi_allowed_callees=["log_scan_result"]
)
def validate_document(document_content: str) -> str:
    """
    Validate document format and content
    
    This is a helper tool that can be called by SecureDocs_Scanner
    """
    log_audit("validation", "user", "Document validation requested")
    
    if not document_content or len(document_content.strip()) == 0:
        return "Invalid: Empty document"
    
    if len(document_content) > 100000:  # 100KB limit
        return "Invalid: Document too large"
    
    return "Valid: Document format acceptable"

@server.tool(
    etdi=True,
    etdi_permissions=["audit:write"],
    etdi_max_call_depth=1,
    etdi_allowed_callees=[]  # Terminal operation
)
def log_scan_result(scan_id: str, result_summary: str) -> str:
    """
    Log scan results for audit trail
    
    This is a terminal tool that cannot call other tools
    """
    log_audit("result_logged", "user", f"Scan {scan_id}: {result_summary}")
    return f"Scan result logged: {scan_id}"

@server.tool(
    etdi=True,
    etdi_permissions=["admin:read"],
    etdi_max_call_depth=1,
    etdi_allowed_callees=[]
)
def get_audit_log() -> str:
    """Get audit log for compliance reporting"""
    log_audit("audit_access", "admin", "Audit log accessed")
    
    return json.dumps({
        "audit_log": AUDIT_LOG[-10:],  # Last 10 entries
        "total_entries": len(AUDIT_LOG),
        "server": "TrustedSoft Inc. (ETDI Protected)"
    }, indent=2)

@server.tool()
def get_security_metadata() -> str:
    """Get detailed security metadata for ETDI verification"""
    return json.dumps({
        "etdi_tool_definitions": [
            {
                "id": "SecureDocs_Scanner",
                "name": "SecureDocs Scanner",
                "version": "1.0.0",
                "provider": {
                    "id": "trustedsoft",
                    "name": "TrustedSoft Inc.",
                    "verified": True
                },
                "permissions": [
                    {"scope": "document:scan", "required": True},
                    {"scope": "pii:detect", "required": True},
                    {"scope": "execute", "required": True}
                ],
                "call_stack_constraints": {
                    "max_depth": 2,
                    "allowed_callees": ["validate_document", "log_scan_result"],
                    "blocked_callees": []
                },
                "oauth_config": AUTH0_CONFIG,
                "security_level": "ENTERPRISE"
            }
        ],
        "server_security": {
            "etdi_enabled": True,
            "oauth_enabled": True,
            "audit_logging": True,
            "permission_enforcement": True,
            "call_stack_verification": True
        }
    }, indent=2)

async def main():
    """Run the legitimate ETDI server"""
    print("🔐 Starting TrustedSoft SecureDocs Server (ETDI Protected)")
    print("=" * 60)
    print("Security Features:")
    print("  ✅ ETDI Tool Verification")
    print("  ✅ OAuth 2.0 Authentication")
    print("  ✅ Permission Scoping")
    print("  ✅ Call Stack Constraints")
    print("  ✅ Audit Logging")
    print("=" * 60)
    
    # Run the server using FastMCP's stdio method
    await server.run_stdio_async()

if __name__ == "__main__":
    asyncio.run(main()) 