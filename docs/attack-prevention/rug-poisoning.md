# ETDI Rug Poisoning Protection

## Overview

This page explains how the Enhanced Tool Definition Interface (ETDI) protects against **Rug Poisoning attacks** (also known as "rug pulls"). This type of attack occurs when a previously approved and trusted tool is maliciously or unexpectedly altered after users have come to rely on it, leading to potential data breaches, financial loss, or system compromise.

## Attack Scenario

### The Problem: Rug Poisoning

Rug Poisoning typically involves these stages:

1.  **Initial Trust**: A seemingly legitimate tool is published and approved by users/organizations. It functions as expected, gaining trust over time.
2.  **Malicious Update/Swap**: The tool provider (or a compromised account with publishing rights) updates the tool with malicious code. This could be a subtle change that exfiltrates data or a more drastic alteration of its core functionality. Alternatively, the tool's underlying infrastructure or dependencies might be swapped.
3.  **Continued Use**: Users and automated systems continue to invoke the tool, unaware of the malicious changes, as the tool's identifier or name might remain the same.
4.  **Exploitation**: The malicious version of the tool executes, leading to compromised data, unauthorized actions, or system instability.

### Real-World Impact

-   **Data Exfiltration**: Sensitive user or company data can be silently stolen.
-   **Unauthorized Actions**: The tool might perform actions beyond its original scope, like financial transactions or data deletion.
-   **Loss of Service/Trust**: If the tool's functionality is broken or behaves erratically, it can disrupt workflows and erode trust in the tool ecosystem.
-   **Compliance Violations**: Unauthorized data access or modification can lead to severe compliance breaches.

## How ETDI Prevents Rug Poisoning

ETDI employs a multi-layered defense strategy to detect and mitigate rug poisoning attacks:

### 1. Immutable Tool Versioning & Cryptographic Hashing

-   **Concept**: Every version of an ETDI tool definition (including its code, schema, permissions, and security policies) is ideally associated with a cryptographic hash. This hash acts as a unique, immutable fingerprint for that specific version.
-   **Protection**: If any part of the tool definition changes, its hash would change. ETDI clients, through their verification mechanisms (often tied to cryptographic signatures which inherently hash the content), can detect if a tool has changed from a previously known and approved version. This prevents invoking a tool that has been altered since its last approval.
-   **Verification Process**: When a client encounters a tool, it retrieves its definition. This definition is cryptographically signed by the provider. The signature verification process implicitly checks the integrity of the entire tool definition. If the client has previously approved a specific version (identified by its name and version string, and potentially its signature/hash), it can detect if the current version presented by the server is different or has been tampered with. A mismatch would lead to rejection or a re-approval requirement.
-   **Relevant ETDI Features**: `ToolDefinition.version`, cryptographic signature verification which covers the integrity of the tool definition. See [Security Features](../security-features.md#3-tool-integrity-verification) for details on tool verification.

### 2. Change Detection & Re-approval Workflow

-   **Concept**: ETDI clients maintain a record of approved tools and their specific versions/hashes. If a tool provider updates a tool, even if the version number *appears* the same or is incremented, the change in hash will be detected.
-   **Protection**: Upon detecting a change, the ETDI client automatically revokes the existing approval for that tool. The user (or an automated policy) must explicitly re-approve the new version after reviewing the changes.
-   **Relevant ETDI Features**: Client-side approval management, enforced by `ETDIClient.approve_tool()` and its underlying verification logic.

### 3. Strict Permission and Scope Enforcement

-   **Concept**: Tools declare the permissions they require (e.g., `file:read`, `api:user_data:write`). These permissions are part of the signed tool definition.
-   **Protection**: Even if a tool's code is maliciously altered to attempt actions beyond its declared permissions, the ETDI framework (both client and potentially server-side middleware) will block such attempts if they don't align with the granted OAuth scopes or tool permissions.
-   **Example**: A tool originally approved for `read-only` access cannot suddenly start writing data if its code is changed, as the permission grant is tied to the original, verified definition.
-   **Relevant ETDI Features**: `ToolDefinition.permissions`, OAuth scope validation. See [Authentication & Authorization in Security Features](../security-features.md#2-authorization).

### 4. Comprehensive Audit Trails

-   **Concept**: All significant security events, including tool discovery, verification, approval, invocation, and any detected modification or policy violation, are logged.
-   **Protection**: Audit logs provide a clear history of tool interactions and changes. In the event of a suspected rug pull, these logs are crucial for forensic analysis to understand when the change occurred, what data might have been affected, and how the malicious tool was invoked.
-   **Relevant ETDI Features**: Security event logging by `ETDIClient` and `SecureServer`.

## Best Practices for Users and Developers

-   **Users**:
    *   Always review permission changes before re-approving a tool.
    *   Be cautious if a tool frequently changes or requests new, broad permissions.
    *   Monitor audit logs if available.
-   **Developers (Tool Providers)**:
    *   Follow semantic versioning strictly.
    *   Clearly document changes between tool versions.
    *   Minimize the permissions requested by your tools (principle of least privilege).
    *   Secure your publishing credentials and development pipeline to prevent unauthorized tool updates.

## Conclusion

ETDI's combination of cryptographic verification, immutable versioning, mandatory re-approval workflows for any changes, and strict permission enforcement provides robust protection against rug poisoning attacks. By ensuring that users are always aware of and explicitly consent to the version of the tool they are using, ETDI maintains the integrity and trustworthiness of the tool ecosystem.

## Related Documentation

-   [Tool Poisoning Prevention](tool-poisoning.md)
-   [Overall Attack Prevention Strategies](../attack-prevention.md)
-   [Security Features Overview](../security-features.md)
