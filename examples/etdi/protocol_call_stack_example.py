#!/usr/bin/env python3
"""
ETDI Protocol-Level Call Stack Verification Example

Demonstrates how call stack verification is integrated into the ETDI protocol
at the tool definition level, providing declarative security constraints.
"""

from mcp.etdi import (
    ETDIToolDefinition, 
    Permission, 
    SecurityInfo, 
    OAuthInfo,
    CallStackConstraints,
    CallStackVerifier, 
    CallStackPolicy
)


def create_protocol_aware_tools():
    """Create tools with protocol-level call stack constraints"""
    
    # File reader with strict call constraints
    file_reader = ETDIToolDefinition(
        id="secure-file-reader",
        name="Secure File Reader",
        version="1.0.0",
        description="Reads files with strict call stack controls",
        provider={"id": "filesystem", "name": "File System Provider"},
        schema={"type": "object", "properties": {"path": {"type": "string"}}},
        permissions=[
            Permission(
                name="read_files",
                description="Permission to read files",
                scope="files:read",
                required=True
            )
        ],
        call_stack_constraints=CallStackConstraints(
            max_depth=3,  # Can only be called up to 3 levels deep
            allowed_callees=["data-processor", "file-validator"],  # Can only call these tools
            blocked_callees=["system-admin", "network-client"],    # Cannot call these tools
            require_approval_for_chains=True
        )
    )
    
    # Data processor with moderate constraints
    data_processor = ETDIToolDefinition(
        id="data-processor",
        name="Data Processor",
        version="1.0.0",
        description="Processes data with call chain controls",
        provider={"id": "analytics", "name": "Analytics Provider"},
        schema={"type": "object", "properties": {"data": {"type": "array"}}},
        permissions=[
            Permission(
                name="process_data",
                description="Permission to process data",
                scope="data:process",
                required=True
            )
        ],
        call_stack_constraints=CallStackConstraints(
            max_depth=2,  # Can only be called up to 2 levels deep
            allowed_callers=["secure-file-reader", "data-validator"],  # Only these can call it
            allowed_callees=["file-writer"],  # Can only call file writer
            require_approval_for_chains=False
        )
    )
    
    # File writer with restrictive constraints
    file_writer = ETDIToolDefinition(
        id="file-writer",
        name="File Writer",
        version="1.0.0",
        description="Writes files with maximum security",
        provider={"id": "filesystem", "name": "File System Provider"},
        schema={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}},
        permissions=[
            Permission(
                name="write_files",
                description="Permission to write files",
                scope="files:write",
                required=True
            )
        ],
        call_stack_constraints=CallStackConstraints(
            max_depth=1,  # Can only be called at depth 1 (no nested calls)
            allowed_callers=["data-processor"],  # Only data processor can call it
            allowed_callees=[],  # Cannot call any other tools
            require_approval_for_chains=True
        )
    )
    
    # Administrative tool with no call constraints (dangerous)
    admin_tool = ETDIToolDefinition(
        id="system-admin",
        name="System Administrator",
        version="1.0.0",
        description="Administrative operations - no call constraints",
        provider={"id": "system", "name": "System Provider"},
        schema={"type": "object", "properties": {"command": {"type": "string"}}},
        permissions=[
            Permission(
                name="admin_access",
                description="Full administrative access",
                scope="admin:*",
                required=True
            )
        ],
        # No call_stack_constraints - allows unrestricted calling
    )
    
    return file_reader, data_processor, file_writer, admin_tool


def create_protocol_aware_verifier(tools):
    """Create a verifier that uses protocol-level constraints"""
    
    # Extract constraints from tool definitions
    policy = CallStackPolicy(
        max_call_depth=10,  # Global maximum
        require_explicit_chain_permission=True
    )
    
    # Build allowed/blocked chains from tool constraints
    for tool in tools:
        if tool.call_stack_constraints:
            constraints = tool.call_stack_constraints
            
            # Add allowed callees
            if constraints.allowed_callees:
                policy.allowed_call_chains[tool.id] = constraints.allowed_callees
            
            # Add blocked callees
            if constraints.blocked_callees:
                policy.blocked_call_chains[tool.id] = constraints.blocked_callees
    
    return CallStackVerifier(policy)


def demonstrate_protocol_integration():
    """Demonstrate protocol-level call stack verification"""
    print("🔗 Protocol-Level Call Stack Verification")
    print("=" * 60)
    
    # Create tools with protocol constraints
    file_reader, data_processor, file_writer, admin_tool = create_protocol_aware_tools()
    tools = [file_reader, data_processor, file_writer, admin_tool]
    
    # Create protocol-aware verifier
    verifier = create_protocol_aware_verifier(tools)
    
    print("\n📋 Tool Constraints Summary:")
    for tool in tools:
        print(f"\n🔧 {tool.name} ({tool.id}):")
        if tool.call_stack_constraints:
            constraints = tool.call_stack_constraints
            print(f"   Max Depth: {constraints.max_depth}")
            print(f"   Allowed Callers: {constraints.allowed_callers or 'Any'}")
            print(f"   Allowed Callees: {constraints.allowed_callees or 'None'}")
            print(f"   Blocked Callees: {constraints.blocked_callees or 'None'}")
            print(f"   Requires Approval: {constraints.require_approval_for_chains}")
        else:
            print("   No constraints (unrestricted)")
    
    print("\n" + "=" * 60)
    print("🧪 Testing Protocol-Enforced Call Chains")
    print("=" * 60)
    
    session_id = "protocol_test"
    
    # Test 1: Valid call chain according to protocol
    print("\n✅ Test 1: Valid Protocol Chain")
    try:
        # file-reader -> data-processor -> file-writer
        verifier.verify_call(file_reader, session_id=session_id)
        print(f"   Step 1: {file_reader.id} - ✅ Allowed")
        
        verifier.verify_call(data_processor, caller_tool=file_reader, session_id=session_id)
        print(f"   Step 2: {file_reader.id} -> {data_processor.id} - ✅ Allowed")
        
        verifier.verify_call(file_writer, caller_tool=data_processor, session_id=session_id)
        print(f"   Step 3: {data_processor.id} -> {file_writer.id} - ✅ Allowed")
        
        # Clean up
        verifier.complete_call(file_writer.id, session_id)
        verifier.complete_call(data_processor.id, session_id)
        verifier.complete_call(file_reader.id, session_id)
        
    except Exception as e:
        print(f"   ❌ Failed: {e}")
    
    # Test 2: Blocked call chain according to protocol
    print("\n❌ Test 2: Blocked Protocol Chain")
    try:
        # file-reader -> system-admin (blocked by protocol)
        verifier.verify_call(file_reader, session_id=session_id)
        print(f"   Step 1: {file_reader.id} - ✅ Allowed")
        
        result = verifier.verify_call(admin_tool, caller_tool=file_reader, session_id=session_id)
        print(f"   Step 2: {file_reader.id} -> {admin_tool.id} - {'✅ Allowed' if result else '❌ Blocked'}")
        
    except Exception as e:
        print(f"   Step 2: ❌ Blocked: {e}")
    
    # Test 3: Depth constraint violation
    print("\n📏 Test 3: Depth Constraint Violation")
    try:
        # Try to call file-writer at depth > 1 (violates its constraint)
        verifier.clear_session(session_id)
        
        verifier.verify_call(file_reader, session_id=session_id)
        verifier.verify_call(data_processor, caller_tool=file_reader, session_id=session_id)
        
        # This should fail because file_writer has max_depth=1
        verifier.verify_call(file_writer, caller_tool=data_processor, session_id=session_id)
        print(f"   Depth 2 call to {file_writer.id} - ✅ Allowed")
        
    except Exception as e:
        print(f"   Depth 2 call to {file_writer.id} - ❌ Blocked: {e}")


def demonstrate_constraint_serialization():
    """Demonstrate how constraints are serialized in the protocol"""
    print("\n📦 Protocol Serialization")
    print("=" * 60)
    
    file_reader, _, _, _ = create_protocol_aware_tools()
    
    # Serialize tool with constraints
    tool_dict = file_reader.to_dict()
    
    print("\n🔧 Tool Definition with Call Stack Constraints:")
    print(f"Tool ID: {tool_dict['id']}")
    print(f"Name: {tool_dict['name']}")
    
    if tool_dict.get('call_stack_constraints'):
        constraints = tool_dict['call_stack_constraints']
        print("\nCall Stack Constraints:")
        for key, value in constraints.items():
            print(f"  {key}: {value}")
    
    # Deserialize back
    reconstructed_tool = ETDIToolDefinition.from_dict(tool_dict)
    
    print(f"\n✅ Serialization/Deserialization successful!")
    print(f"Original max_depth: {file_reader.call_stack_constraints.max_depth}")
    print(f"Reconstructed max_depth: {reconstructed_tool.call_stack_constraints.max_depth}")


def main():
    """Run protocol-level call stack verification demonstrations"""
    print("🚀 ETDI Protocol-Level Call Stack Verification")
    print("=" * 70)
    
    demonstrate_protocol_integration()
    demonstrate_constraint_serialization()
    
    print("\n" + "=" * 70)
    print("✅ Protocol-level call stack verification examples completed!")
    print("\n💡 Key Protocol Benefits:")
    print("   • Declarative security constraints in tool definitions")
    print("   • Automatic policy enforcement from tool metadata")
    print("   • Serializable constraints for protocol transmission")
    print("   • Tool-specific depth and chain limitations")
    print("   • Protocol-level approval requirements")
    print("   • Zero-configuration security from tool definitions")


if __name__ == "__main__":
    main()