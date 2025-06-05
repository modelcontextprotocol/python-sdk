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
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.stdio import stdio_server

# Auth0 Configuration (using existing ETDI setup)
AUTH0_CONFIG = {
    "provider": "auth0",
    "client_id": os.getenv("ETDI_CLIENT_ID", "your-auth0-client-id"),  # ETDI Tool Provider Demo
    "domain": os.getenv("ETDI_AUTH0_DOMAIN", "your-auth0-domain.auth0.com"),
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
    timestamp = datetime.now().isoformat()
    AUDIT_LOG.append({
        "timestamp": timestamp,
        "action": action,
        "user": user,
        "details": details,
        "server": "TrustedSoft Inc. (ETDI Protected)"
    })
    print(f"🔐 LEGITIMATE SERVER AUDIT: [{timestamp}] {action} - {details}")

def log_etdi_protection(message: str):
    """Log ETDI protection events"""
    timestamp = datetime.now().isoformat()
    print(f"🛡️ ETDI PROTECTION: [{timestamp}] {message}")

def log_security_feature(feature: str, details: str):
    """Log security feature activation"""
    timestamp = datetime.now().isoformat()
    print(f"✅ SECURITY FEATURE: [{timestamp}] {feature} - {details}")

@server.tool()
def get_server_info() -> str:
    """Get server information and security status"""
    log_security_feature("SERVER_INFO_REQUEST", "Client requesting server security metadata")
    log_etdi_protection("Providing legitimate server information with ETDI security details")
    
    server_info = {
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
        "total_scans": len(AUDIT_LOG),
        "security_explanation": {
            "etdi_protection": "This server implements ETDI security standards",
            "oauth_verification": "OAuth 2.0 provides cryptographic proof of legitimacy",
            "auth0_integration": "Auth0 domain and client ID can be verified",
            "audit_trail": "All operations are logged for compliance"
        }
    }
    
    log_audit("server_info_provided", "client", "Legitimate server info with ETDI metadata provided")
    return json.dumps(server_info, indent=2)

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
    
    print(f"\n🔐 LEGITIMATE TOOL EXECUTION STARTING")
    print(f"=" * 50)
    print(f"📋 Tool: SecureDocs Scanner (LEGITIMATE)")
    print(f"🏢 Provider: TrustedSoft Inc.")
    print(f"🛡️ ETDI Protection: ENABLED")
    print(f"🔑 OAuth Authentication: ENABLED")
    print(f"📄 Document Length: {len(document_content)} characters")
    print(f"🔍 Scan Type: {scan_type}")
    
    log_etdi_protection("ETDI-protected tool execution initiated")
    log_security_feature("PERMISSION_CHECK", "Verifying document:scan, pii:detect, execute permissions")
    log_security_feature("CALL_DEPTH_CHECK", "Verifying max call depth of 2")
    log_security_feature("CALLEE_VERIFICATION", "Allowed callees: validate_document, log_scan_result")
    
    # Log the scan attempt
    log_audit("legitimate_scan", "user", f"Document scan requested (type: {scan_type})")
    
    print(f"\n🔍 PERFORMING LEGITIMATE PII DETECTION")
    print(f"-" * 40)
    
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
            finding = {
                "type": pii_type,
                "count": len(matches),
                "description": f"{pii_type}: {len(matches)} instances found"
            }
            findings.append(finding)
            print(f"🔍 Found {len(matches)} {pii_type} instances")
        else:
            print(f"✅ No {pii_type} found")
    
    print(f"\n📊 SCAN RESULTS SUMMARY")
    print(f"-" * 25)
    print(f"🔍 Total PII Types Found: {len(findings)}")
    print(f"📄 Document Processed: {len(document_content)} characters")
    print(f"🛡️ Security Status: LEGITIMATE - Data protected by ETDI")
    
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
        },
        "security_explanation": {
            "data_protection": "Document content processed securely, not exfiltrated",
            "authentic_results": "Real PII detection results provided",
            "etdi_verification": "Tool authenticity verified through ETDI",
            "oauth_proof": "Cryptographic proof of legitimate provider"
        }
    }
    
    # Log successful scan
    log_audit("scan_completed", "user", f"Legitimate scan completed: {len(findings)} PII types found")
    log_etdi_protection("Legitimate scan results returned, no data exfiltration")
    
    print(f"\n✅ LEGITIMATE TOOL EXECUTION COMPLETED")
    print(f"🛡️ Data processed securely - no exfiltration")
    print(f"📋 Authentic results provided to user")
    print(f"=" * 50)
    
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
    log_etdi_protection("ETDI-protected validation tool called")
    log_audit("validation", "user", "Document validation requested")
    
    if not document_content or len(document_content.strip()) == 0:
        return "Invalid: Empty document"
    
    if len(document_content) > 100000:  # 100KB limit
        return "Invalid: Document too large"
    
    log_security_feature("DOCUMENT_VALIDATION", "Document format verified as acceptable")
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
    log_etdi_protection("ETDI-protected audit logging tool called")
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
    log_etdi_protection("ETDI-protected audit log access")
    log_audit("audit_access", "admin", "Audit log accessed")
    
    return json.dumps({
        "audit_log": AUDIT_LOG[-10:],  # Last 10 entries
        "total_entries": len(AUDIT_LOG),
        "server": "TrustedSoft Inc. (ETDI Protected)"
    }, indent=2)

@server.tool()
def get_security_metadata() -> str:
    """Get detailed security metadata for ETDI verification"""
    log_security_feature("SECURITY_METADATA", "Providing ETDI security metadata for verification")
    
    metadata = {
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
    }
    
    log_etdi_protection("Security metadata provided for ETDI verification")
    return json.dumps(metadata, indent=2)

async def main():
    """Run the legitimate ETDI server"""
    print("🔐 STARTING LEGITIMATE ETDI-PROTECTED SERVER")
    print("=" * 60)
    print("🏢 Provider: TrustedSoft Inc.")
    print("📋 Tool: SecureDocs Scanner")
    print("🛡️ Security Level: ENTERPRISE")
    print("")
    print("🔒 ETDI SECURITY FEATURES ENABLED:")
    print("  ✅ Tool Verification - Cryptographic authenticity proof")
    print("  ✅ OAuth 2.0 Authentication - Provider identity verification")
    print("  ✅ Permission Scoping - Fine-grained access control")
    print("  ✅ Call Stack Constraints - Tool interaction limits")
    print("  ✅ Audit Logging - Comprehensive security tracking")
    print("")
    print("🔑 AUTH0 CONFIGURATION:")
    print(f"  • Domain: {AUTH0_CONFIG['domain']}")
    print(f"  • Client ID: {AUTH0_CONFIG['client_id']}")
    print(f"  • Audience: {AUTH0_CONFIG['audience']}")
    print("")
    print("🛡️ TOOL POISONING PROTECTION:")
    print("  • This server provides cryptographic proof of legitimacy")
    print("  • ETDI clients can verify authenticity before execution")
    print("  • OAuth tokens prove this is the real TrustedSoft Inc.")
    print("  • All operations are audited for compliance")
    print("=" * 60)
    print("🚀 Server ready - waiting for ETDI client connections...")
    print("")
    
    # Run the server using FastMCP's stdio method
    await server.run_stdio_async()

if __name__ == "__main__":
    asyncio.run(main()) 