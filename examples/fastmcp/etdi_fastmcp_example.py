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