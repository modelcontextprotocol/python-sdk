# Attack Prevention

ETDI provides robust protection against advanced AI security threats, including tool poisoning, rug poisoning, and unauthorized tool access. This page summarizes the core attack prevention strategies and how to implement them.

## Tool Poisoning Prevention

Tool poisoning occurs when a malicious actor introduces or replaces a tool with a compromised version. ETDI prevents this via:

- **Cryptographic Signatures**: All tools are signed and verified at registration and invocation. See [Tool Poisoning Demo](attack-prevention/tool-poisoning.md) for details.
- **Audit Logs for Monitoring**: Comprehensive audit logs capture tool activity, which can be fed into external monitoring systems to detect anomalous behavior and policy violations.
- **Approval Workflow**: Users must explicitly approve new or changed tools before use.

### Example: Secure Tool Registration

```python
@server.tool("secure_file_read", require_signature=True)
async def secure_file_read(path: str) -> str:
    # Implementation with cryptographic verification
    ...
```

## Rug Poisoning Protection

Rug poisoning ("rug pull") is when a tool is swapped or modified after initial approval. ETDI detects and blocks this via:

- **Immutable Versioning**: Every tool version is cryptographically hashed and tracked.
- **Change Detection**: Any change to code, permissions, or metadata triggers reapproval.
- **Audit Trails**: All tool changes and approvals are logged for forensics.

Details on how ETDI mitigates this can be found in [Rug Poisoning Protection](attack-prevention/rug-poisoning.md).

### Example: Versioned Tool Approval

```python
# User approves tool version 1.0
await client.approve_tool(tool_id, version="1.0")

# If the tool changes (hash mismatch), approval is revoked until reapproved by the user.
```

## Call Stack Security

Call stack security is crucial for preventing privilege escalation and unauthorized tool chaining, ensuring that a sequence of tool calls doesn't lead to unintended capabilities or data access.

ETDI implements call stack security through several mechanisms:

-   **Maximum Call Depth**: Defines how many levels deep a tool invocation chain can go. This prevents runaway recursive calls or overly complex interactions that might obscure malicious activity or lead to denial-of-service.
    ```python
    # Part of SecurityPolicy or individual tool definition
    # server = SecureServer(security_policy=SecurityPolicy(max_call_depth=5))
    @server.tool("my_tool", etdi_max_call_depth=3)
    async def my_tool_impl(): ...
    ```

-   **Allowed/Blocked Callees**: Tool definitions can specify which other tools they are explicitly allowed to call, or which ones they are explicitly forbidden from calling. This creates a more predictable and constrained interaction graph.
    ```python
    # Part of SecurityPolicy or individual tool definition
    # policy = SecurityPolicy(allowed_callees={"tool_a": ["tool_b"]})
    @server.tool("tool_a", etdi_allowed_callees=["tool_b", "tool_c"])
    async def tool_a_impl(): ...

    @server.tool("sensitive_tool", etdi_blocked_callees=["network_tool", "external_api_tool"])
    async def sensitive_tool_impl(): ...
    ```

-   **Caller/Callee Authorization**: Beyond just allowed/blocked lists, ETDI can enforce mutual authorization. This means not only must `tool_A` be allowed to call `tool_B`, but `tool_B` must also be configured to accept calls from `tool_A`. This is typically managed through permission and scope checks tied to the identities of the tools themselves (if they have their own service identities) or the user context propagating the call.

-   **Verification**: The ETDI client and/or server-side middleware inspects the call stack at each invocation. If a call violates any of these constraints (e.g., exceeds max depth, calls a blocked tool, or lacks authorization), the invocation is rejected before the tool code executes.

These features collectively ensure that tool interactions are confined to well-defined boundaries, significantly reducing the attack surface.

Refer to example scripts like `protocol_call_stack_example.py` and `caller_callee_authorization_example.py` in the [Examples & Demos](examples/index.md) section for practical implementations.

## Real-World Attack Scenarios

- **Tool Poisoning Demo**: See the detailed [Tool Poisoning Prevention page](attack-prevention/tool-poisoning.md) and its associated demo scripts in `examples/etdi/tool_poisoning_demo/`.
- **Rug Poisoning Detection**: The framework automatically detects and blocks unauthorized tool changes as detailed in [Rug Poisoning Protection](attack-prevention/rug-poisoning.md).

## Best Practices

- Always require tool signatures in production.
- Regularly audit tool approval and change logs.
- Use strict call chain policies (max depth, allowed/blocked callees) for sensitive operations. 