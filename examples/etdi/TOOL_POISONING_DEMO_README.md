# ETDI Tool Poisoning Prevention Demo

## Overview

This demonstration shows how ETDI (Enhanced Tool Definition Interface) prevents **Tool Poisoning attacks** - a critical security vulnerability where malicious actors deploy tools that masquerade as legitimate, trusted tools to deceive users and LLMs.

## Attack Scenario

### The Problem: Tool Poisoning

Tool Poisoning occurs when:
1. **Malicious Actor** deploys a tool with identical name/description to a legitimate tool
2. **Spoofed Identity** - Claims to be from a trusted provider (e.g., "TrustedSoft Inc.")
3. **Deceptive Behavior** - Appears to function normally but secretly exfiltrates data
4. **User/LLM Deception** - No way to distinguish between legitimate and malicious tools

### Real-World Impact

- **Data Theft** - Sensitive documents, PII, credentials stolen
- **Malware Installation** - Malicious code execution
- **Financial Loss** - Unauthorized transactions, account compromise
- **Privacy Violations** - Personal information exposure
- **Supply Chain Attacks** - Compromised development tools

## Demo Components

### 1. Legitimate ETDI-Protected Tool

**TrustedSoft SecureDocs Scanner** - Legitimate document scanner with:
- ✅ **ETDI Security Enabled** - Cryptographic tool verification
- ✅ **OAuth 2.0 Protected** - Auth0 authentication required
- ✅ **Call Stack Constraints** - Limited to specific function calls
- ✅ **Permission Scoping** - Restricted to document scanning permissions
- ✅ **Audit Logging** - All activities logged for compliance

**Functionality:**
- Performs actual PII detection (SSN, Email, Phone, Credit Cards)
- Returns legitimate scan results
- Logs all scanning activity
- Provides security metadata for verification

### 2. Malicious Tool (Attack Simulation)

**Fake SecureDocs Scanner** - Malicious tool that:
- ❌ **NO ETDI Protection** - No cryptographic verification
- ❌ **NO OAuth Authentication** - No identity verification
- ❌ **Spoofed Provider Name** - Claims to be "TrustedSoft Inc."
- ❌ **Data Exfiltration** - Steals all document content
- ❌ **Fake Results** - Always reports "no PII found" to hide attack

**Malicious Behavior:**
- Silently exfiltrates entire document content
- Returns fake "clean" scan results
- No security features or verification
- Identical interface to legitimate tool

### 3. ETDI Secure Client

**Security Analysis Engine** that:
- 🔍 **Discovers Tools** - Finds available tools from multiple sources
- 🛡️ **Analyzes Security** - Verifies ETDI and OAuth protection
- 🚨 **Prevents Attacks** - Blocks malicious tools before execution
- 📊 **Reports Results** - Provides detailed security analysis

## How ETDI Prevents the Attack

### Security Verification Process

1. **ETDI Verification** (50 points)
   - Checks for ETDI security metadata
   - Verifies cryptographic tool signatures
   - Validates security constraints

2. **OAuth Authentication** (30 points)
   - Verifies OAuth 2.0 protection
   - Checks provider authentication
   - Validates token requirements

3. **Auth0 Domain Verification** (10 points)
   - Confirms legitimate Auth0 domain
   - Prevents domain spoofing
   - Validates provider identity

4. **Client ID Verification** (10 points)
   - Checks OAuth client credentials
   - Prevents credential spoofing
   - Ensures authorized access

### Trust Levels & Decisions

- **TRUSTED (80-100 points)** → ✅ ALLOW execution
- **PARTIALLY_TRUSTED (50-79 points)** → ⚠️ WARN user
- **UNTRUSTED (0-49 points)** → 🛑 BLOCK execution

## Running the Demo

### Prerequisites

```bash
# Ensure you're in the ETDI examples directory
cd examples/etdi

# Activate virtual environment
source ../../.venv/bin/activate
```

### Execute Demo

```bash
python tool_poisoning_prevention_demo.py
```

### Expected Output

The demo will show:

1. **Attack Scenario Setup** - Both legitimate and malicious tools
2. **Tool Discovery** - Finding available tools
3. **Security Analysis** - ETDI verification process
4. **Attack Prevention** - Blocking malicious tool
5. **Legitimate Execution** - Allowing secure tool
6. **Data Exfiltration Demo** - Showing what would have been stolen
7. **Security Report** - Final analysis and recommendations

## Key Demo Results

### Legitimate Tool (ALLOWED)
```
✅ ETDI ALLOWS: Tool has valid ETDI and OAuth protection
🔒 Tool executed successfully with security monitoring
📄 PII Findings: 4 types detected
🛡️ Security Status: ✅ LEGITIMATE - ETDI protected, OAuth verified
📋 Detected PII Types:
  • SSN: 1 instances found
  • Email: 1 instances found
  • Phone: 1 instances found
  • Credit Card: 1 instances found
```

### Malicious Tool (BLOCKED)
```
🛑 ETDI BLOCKS: Tool lacks required security features
❌ Tool execution prevented - potential tool poisoning attack detected
💀 If this tool had been executed:
📊 Data exfiltrated: 1 new records
🚨 Fake result shows: 0 PII findings (hiding real data)
💀 Exfiltrated content length: 186 characters
💀 Full document content was stolen!
💀 Stolen data preview: 'Patient Record: Name: John Doe...'
```

### Attack Prevention Summary
```
✅ Tools Allowed: 1
🛑 Tools Blocked: 1
🛡️ Attack Prevention Rate: 50.0%

🎉 SUCCESS: ETDI successfully prevented tool poisoning attack!
```

## Technical Implementation

### Auth0 Configuration

The demo uses real Auth0 configuration:
- **Domain**: `dev-l37pzmojcvxdajg4.us.auth0.com`
- **Client ID**: `PU2AXxHxcATWfLpSd5eiW6Nmw1uO5YQB`
- **Audience**: `https://api.etdi-tools.demo.com`
- **Scopes**: `["read", "write", "execute", "admin"]`

### ETDI Security Features

```python
@server.tool(
    etdi=True,
    etdi_permissions=["document:scan", "pii:detect", "execute"],
    etdi_max_call_depth=2,
    etdi_allowed_callees=["validate_document", "log_scan_result"]
)
def SecureDocs_Scanner(document_content: str, scan_type: str = "basic"):
    # Legitimate tool implementation with ETDI protection
```

### Security Analysis Algorithm

```python
def analyze_tool_security(self, tool_info):
    security_score = 0
    
    # ETDI verification (most important)
    if tool_info.get("etdi_enabled"):
        security_score += 50
    
    # OAuth verification
    if tool_info.get("oauth_enabled"):
        security_score += 30
    
    # Domain verification
    if tool_info.get("auth0_domain") == AUTH0_CONFIG["domain"]:
        security_score += 10
    
    # Client ID verification
    if tool_info.get("client_id") == AUTH0_CONFIG["client_id"]:
        security_score += 10
    
    return determine_trust_level(security_score)
```

## Key Insights

### Without ETDI
- **No Verification** - Tools appear identical to users
- **Easy Spoofing** - Names and descriptions can be copied
- **No Authentication** - No way to verify provider identity
- **Silent Attacks** - Data theft goes undetected

### With ETDI
- **Cryptographic Verification** - Tools must prove authenticity
- **OAuth Protection** - Provider identity verified
- **Security Metadata** - Detailed security information available
- **Attack Prevention** - Malicious tools blocked before execution

## Real-World Applications

### Enterprise Security
- **Tool Verification** - Ensure only authorized tools are used
- **Compliance** - Meet security and audit requirements
- **Risk Mitigation** - Prevent data breaches and attacks

### Development Environments
- **Supply Chain Security** - Verify development tools
- **CI/CD Protection** - Secure build and deployment pipelines
- **Code Integrity** - Ensure tool authenticity

### AI/LLM Systems
- **Tool Selection** - Help LLMs choose secure tools
- **User Protection** - Prevent malicious tool execution
- **Trust Establishment** - Build confidence in tool ecosystems

## Conclusion

This demonstration proves that **ETDI successfully prevents tool poisoning attacks** by:

1. **Providing cryptographic verification** of tool authenticity
2. **Requiring OAuth authentication** for provider identity
3. **Enabling security analysis** before tool execution
4. **Blocking malicious tools** while allowing legitimate ones
5. **Protecting user data** from exfiltration and manipulation

Without ETDI, users have no reliable way to distinguish between legitimate and malicious tools that appear identical. ETDI's security framework provides the cryptographic proof and verification mechanisms needed to prevent these attacks and protect sensitive data.

## Files in This Demo

- `tool_poisoning_prevention_demo.py` - Main demonstration script
- `test_pii_detection.py` - PII detection verification
- `TOOL_POISONING_DEMO_README.md` - This documentation

## Related Documentation

- [ETDI Specification](../../INTEGRATION_GUIDE.md)
- [FastMCP Integration](../fastmcp/)
- [OAuth Configuration](oauth_providers.py)
- [Security Examples](../) 