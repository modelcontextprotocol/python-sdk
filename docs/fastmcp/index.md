# FastMCP with ETDI Integration Example

This page details how to integrate Enhanced Tool Definition Interface (ETDI) security features with the FastMCP decorator API. ETDI security can be enabled and configured using simple boolean flags and parameters directly within the `@server.tool()` decorator.

This approach allows for a declarative way to specify security requirements such as permissions, call stack constraints, and overall ETDI enablement for your tools.

## Example Overview

The `examples/fastmcp/etdi_fastmcp_example.py` script (relative to project root) demonstrates these capabilities.

```python
#!/usr/bin/env python3
"""
FastMCP with ETDI Integration Example

Demonstrates how to use the FastMCP decorator API with ETDI security features
enabled through simple boolean flags and parameters.
"""

from mcp.server.fastmcp import FastMCP

# Create FastMCP server
server = FastMCP("ETDI FastMCP Example")


@server.tool()
def basic_tool(x: int) -> str:
    """A basic tool without ETDI security"""
    return f"Basic result: {x}"


@server.tool(etdi=True)
def simple_etdi_tool(message: str) -> str:
    """A simple tool with ETDI security enabled"""
    return f"ETDI secured: {message}"


@server.tool(
    etdi=True,
    etdi_permissions=["data:read", "files:access"],
    etdi_max_call_depth=3
)
def secure_data_tool(data_id: str) -> str:
    """A tool with specific ETDI permissions and call depth limits"""
    return f"Securely processed data: {data_id}"


@server.tool(
    etdi=True,
    etdi_permissions=["files:write", "storage:modify"],
    etdi_allowed_callees=["secure_data_tool", "validation_tool"],
    etdi_blocked_callees=["admin_tool", "dangerous_tool"]
)
def file_processor(filename: str, content: str) -> str:
    """A tool with call chain restrictions"""
    return f"File {filename} processed with ETDI call chain security"


@server.tool(
    etdi=True,
    etdi_permissions=["admin:read"],
    etdi_max_call_depth=1,
    etdi_allowed_callees=[]  # Cannot call any other tools
)
def admin_info_tool(query: str) -> str:
    """Administrative tool with strict ETDI constraints"""
    return f"Admin info (secured): {query}"


@server.tool(
    etdi=True,
    etdi_permissions=["validation:execute"],
    etdi_max_call_depth=2
)
def validation_tool(data: str) -> str:
    """Validation tool that can be called by other tools"""
    return f"Validated: {data}"


# Example of a tool that would be dangerous without ETDI
@server.tool(
    etdi=True,
    etdi_permissions=["system:execute", "admin:full"],
    etdi_max_call_depth=1,
    etdi_blocked_callees=["*"]  # Cannot call any tools
)
def system_command_tool(command: str) -> str:
    """System command tool with maximum ETDI security"""
    # In a real implementation, this would execute system commands
    # ETDI ensures it can't be called inappropriately or call other tools
    return f"System command executed securely: {command}"


def main():
    """Demonstrate the ETDI-enabled FastMCP server"""
    print("🚀 FastMCP with ETDI Integration Example")
    print("=" * 50)
    
    print("\n📋 Tools registered:")
    
    # Get all registered tools
    tools = server._tool_manager.list_tools()
    
    for tool in tools:
        tool_name = tool.name
        # Check if the original function has ETDI metadata
        original_func = getattr(server._tool_manager._tools.get(tool_name), '_original_function', None)
        
        if hasattr(original_func, '_etdi_enabled') and original_func._etdi_enabled:
            etdi_tool = getattr(original_func, '_etdi_tool_definition', None)
            print(f"\n🔒 {tool_name} (ETDI Secured)")
            print(f"   Description: {tool.description}")
            
            if etdi_tool:
                if etdi_tool.permissions:
                    perms = [p.scope for p in etdi_tool.permissions]
                    print(f"   Permissions: {', '.join(perms)}")
                
                if etdi_tool.call_stack_constraints:
                    constraints = etdi_tool.call_stack_constraints
                    if constraints.max_depth:
                        print(f"   Max Call Depth: {constraints.max_depth}")
                    if constraints.allowed_callees:
                        print(f"   Allowed Callees: {', '.join(constraints.allowed_callees)}")
                    if constraints.blocked_callees:
                        print(f"   Blocked Callees: {', '.join(constraints.blocked_callees)}")
        else:
            print(f"\n📝 {tool_name} (Standard)")
            print(f"   Description: {tool.description}")
    
    print("\n" + "=" * 50)
    print("✅ FastMCP ETDI Integration Complete!")
    print("\n💡 Key Benefits:")
    print("   • Simple boolean flag to enable ETDI security")
    print("   • Declarative permission specification")
    print("   • Call stack depth and chain controls")
    print("   • Automatic ETDI tool definition generation")
    print("   • Seamless integration with existing FastMCP code")
    print("   • Graceful fallback when ETDI not available")
    
    print("\n🔧 Usage Examples:")
    print("   @server.tool(etdi=True)")
    print("   @server.tool(etdi=True, etdi_permissions=['data:read'])")
    print("   @server.tool(etdi=True, etdi_max_call_depth=3)")
    print("   @server.tool(etdi=True, etdi_allowed_callees=['helper'])")


if __name__ == "__main__":
    main()

```

## Key Features Demonstrated

-   **Enabling ETDI**: Simply add `etdi=True` to the `@server.tool()` decorator.
    ```python
    @server.tool(etdi=True)
    def simple_etdi_tool(message: str) -> str: # ...
    ```
-   **Specifying Permissions**: Use the `etdi_permissions` list to declare required OAuth scopes.
    ```python
    @server.tool(
        etdi=True,
        etdi_permissions=["data:read", "files:access"]
    )
    def secure_data_tool(data_id: str) -> str: # ...
    ```
-   **Setting Call Stack Constraints**:
    -   `etdi_max_call_depth`: Integer defining maximum call chain depth.
    -   `etdi_allowed_callees`: List of tool names that this tool is allowed to invoke.
    -   `etdi_blocked_callees`: List of tool names that this tool is explicitly forbidden from invoking (can use `["*"]` to block all calls).
    ```python
    @server.tool(
        etdi=True,
        etdi_permissions=["files:write", "storage:modify"],
        etdi_allowed_callees=["secure_data_tool", "validation_tool"],
        etdi_blocked_callees=["admin_tool", "dangerous_tool"]
    )
    def file_processor(filename: str, content: str) -> str: # ...
    ```
-   **Request Signing**: FastMCP servers support ETDI request signing for secure tool invocations, ensuring authenticity and integrity of every request. See `examples/etdi/request_signing_server_example.py` for usage.

## Benefits

-   **Simplified Security**: Security features are declared alongside the tool definition, making it easy to understand and manage.
-   **Automatic ETDI Definition**: FastMCP handles the creation of the underlying `ETDIToolDefinition` object based on these parameters.
-   **Seamless Integration**: Works with existing FastMCP server and tool structures with minimal changes.
-   **Graceful Fallback**: If the ETDI client or server does not support these specific ETDI extensions, the tool may still function as a standard MCP tool (behavior might depend on MCP library specifics).

By using these decorator parameters, you can incrementally add robust ETDI security to your FastMCP tools.

## Related Documentation

- [Attack Prevention Overview](../attack-prevention.md)
- [Call Stack Security](../attack-prevention.md#call-stack-security)
- [Security Features Overview](../security-features.md) 