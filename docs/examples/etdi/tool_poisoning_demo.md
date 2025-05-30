# ETDI Tool Poisoning Prevention Demo

## Overview

This demonstration shows how ETDI (Enhanced Tool Definition Interface) prevents **Tool Poisoning attacks** - a critical security vulnerability where malicious actors deploy tools that masquerade as legitimate, trusted tools to deceive users and LLMs.

This page is based on the `TOOL_POISONING_DEMO_README.md` found in the `examples/etdi/tool_poisoning_demo/` directory (relative to project root).

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

Details about the legitimate tool, malicious tool, and secure client used in this demo are available in the original README and the demo script (`tool_poisoning_prevention_demo.py` in `examples/etdi/tool_poisoning_demo/`).

### 1. Legitimate ETDI-Protected Tool

**TrustedSoft SecureDocs Scanner** - Legitimate document scanner with ETDI security, OAuth protection, call stack constraints, permission scoping, and audit logging.

### 2. Malicious Tool (Attack Simulation)

**Fake SecureDocs Scanner** - Malicious tool lacking ETDI/OAuth, spoofing provider name, exfiltrating data, and returning fake results.

### 3. ETDI Secure Client

**Security Analysis Engine** that discovers tools, analyzes security (ETDI & OAuth), prevents attacks, and reports results.

## How ETDI Prevents the Attack

ETDI prevents this through a multi-stage verification process, typically involving checking for ETDI metadata, cryptographic signatures, OAuth protection, and provider identity.

## Running the Demo

### Prerequisites

```bash
# Ensure you're in the project root directory
# Activate your virtual environment, e.g.:
# source .venv/bin/activate 
cd examples/etdi/tool_poisoning_demo # Navigate to the demo directory
```

### Execute Demo

```bash
python tool_poisoning_prevention_demo.py
```

*(Refer to the original README in the demo directory for the most up-to-date execution instructions and expected output.)*

## Key Insights

### Without ETDI
- No reliable verification method.
- Easy to spoof tool identities.
- No inherent authentication of the tool provider.
- Silent attacks can go undetected.

### With ETDI
- Cryptographic verification of tool authenticity.
- OAuth protection for provider identity verification.
- Security metadata available for analysis before execution.
- Malicious tools can be blocked proactively.

## Conclusion

ETDI's security framework provides the cryptographic proof and verification mechanisms needed to prevent tool poisoning attacks and protect sensitive data.

## Related Documentation

- [Overall Attack Prevention Strategies](../../attack-prevention.md)
- [Rug Poisoning Protection](../../attack-prevention/rug-poisoning.md)
- [Security Features Overview](../../security-features.md)
- [ETDI Examples Overview](../index.md) 