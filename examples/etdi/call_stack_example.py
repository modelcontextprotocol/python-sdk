#!/usr/bin/env python3
"""
ETDI Call Stack Verification Example

Demonstrates how to use the CallStackVerifier to prevent:
- Unauthorized tool chaining
- Privilege escalation through tool calls
- Circular call dependencies
- Excessive call depth attacks
"""

import asyncio
from mcp.etdi import (
    ETDIToolDefinition, 
    Permission, 
    SecurityInfo, 
    OAuthInfo,
    CallStackVerifier, 
    CallStackPolicy, 
    CallStackViolationType
)


def create_sample_tools():
    """Create sample tools with different permission levels"""
    
    # Basic read-only tool
    read_tool = ETDIToolDefinition(
        id="file-reader",
        name="File Reader",
        version="1.0.0",
        description="Reads files from the filesystem",
        provider={"id": "filesystem", "name": "File System Provider"},
        schema={"type": "object", "properties": {"path": {"type": "string"}}},
        permissions=[
            Permission(
                name="read_files",
                description="Permission to read files",
                scope="files:read",
                required=True
            )
        ]
    )
    
    # Tool that can write files
    write_tool = ETDIToolDefinition(
        id="file-writer",
        name="File Writer", 
        version="1.0.0",
        description="Writes files to the filesystem",
        provider={"id": "filesystem", "name": "File System Provider"},
        schema={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}},
        permissions=[
            Permission(
                name="write_files",
                description="Permission to write files",
                scope="files:write",
                required=True
            )
        ]
    )
    
    # Administrative tool with broad permissions
    admin_tool = ETDIToolDefinition(
        id="system-admin",
        name="System Administrator",
        version="1.0.0", 
        description="Administrative system operations",
        provider={"id": "system", "name": "System Provider"},
        schema={"type": "object", "properties": {"command": {"type": "string"}}},
        permissions=[
            Permission(
                name="admin_access",
                description="Full administrative access",
                scope="admin:*",
                required=True
            )
        ]
    )
    
    # Tool that processes data
    processor_tool = ETDIToolDefinition(
        id="data-processor",
        name="Data Processor",
        version="1.0.0",
        description="Processes and transforms data",
        provider={"id": "analytics", "name": "Analytics Provider"},
        schema={"type": "object", "properties": {"data": {"type": "array"}}},
        permissions=[
            Permission(
                name="process_data",
                description="Permission to process data",
                scope="data:process",
                required=True
            )
        ]
    )
    
    return read_tool, write_tool, admin_tool, processor_tool


def demonstrate_basic_verification():
    """Demonstrate basic call stack verification"""
    print("🔍 Basic Call Stack Verification")
    print("=" * 50)
    
    # Create tools
    read_tool, write_tool, admin_tool, processor_tool = create_sample_tools()
    
    # Create verifier with default policy
    verifier = CallStackVerifier()
    
    # Test normal call sequence
    print("\n✅ Testing normal call sequence:")
    try:
        # Root call - should succeed
        result = verifier.verify_call(read_tool, session_id="session1")
        print(f"   Root call to {read_tool.id}: {'✅ Allowed' if result else '❌ Blocked'}")
        
        # Nested call - should succeed
        result = verifier.verify_call(processor_tool, caller_tool=read_tool, session_id="session1")
        print(f"   Nested call {read_tool.id} -> {processor_tool.id}: {'✅ Allowed' if result else '❌ Blocked'}")
        
        # Complete calls
        verifier.complete_call(processor_tool.id, "session1")
        verifier.complete_call(read_tool.id, "session1")
        
    except Exception as e:
        print(f"   ❌ Error: {e}")


def demonstrate_depth_limiting():
    """Demonstrate call depth limiting"""
    print("\n🔒 Call Depth Limiting")
    print("=" * 50)
    
    # Create tools
    read_tool, write_tool, admin_tool, processor_tool = create_sample_tools()
    
    # Create verifier with strict depth limit
    policy = CallStackPolicy(max_call_depth=3)
    verifier = CallStackVerifier(policy)
    
    tools = [read_tool, write_tool, processor_tool, admin_tool]
    session_id = "depth_test"
    
    print(f"\n📏 Testing depth limit of {policy.max_call_depth}:")
    
    for i, tool in enumerate(tools):
        try:
            caller = tools[i-1] if i > 0 else None
            result = verifier.verify_call(tool, caller_tool=caller, session_id=session_id)
            print(f"   Depth {i}: {tool.id} - {'✅ Allowed' if result else '❌ Blocked'}")
        except Exception as e:
            print(f"   Depth {i}: {tool.id} - ❌ Blocked: {e}")
            break


def demonstrate_circular_detection():
    """Demonstrate circular call detection"""
    print("\n🔄 Circular Call Detection")
    print("=" * 50)
    
    # Create tools
    read_tool, write_tool, admin_tool, processor_tool = create_sample_tools()
    
    # Create verifier that blocks circular calls
    policy = CallStackPolicy(allow_circular_calls=False)
    verifier = CallStackVerifier(policy)
    
    session_id = "circular_test"
    
    print("\n🚫 Testing circular call prevention:")
    try:
        # Start call chain
        verifier.verify_call(read_tool, session_id=session_id)
        print(f"   Call 1: {read_tool.id} - ✅ Allowed")
        
        verifier.verify_call(processor_tool, caller_tool=read_tool, session_id=session_id)
        print(f"   Call 2: {read_tool.id} -> {processor_tool.id} - ✅ Allowed")
        
        # Try to call back to read_tool (circular)
        result = verifier.verify_call(read_tool, caller_tool=processor_tool, session_id=session_id)
        print(f"   Call 3: {processor_tool.id} -> {read_tool.id} - {'✅ Allowed' if result else '❌ Blocked (Circular)'}")
        
    except Exception as e:
        print(f"   Call 3: ❌ Blocked: {e}")


def demonstrate_privilege_escalation_detection():
    """Demonstrate privilege escalation detection"""
    print("\n⚠️ Privilege Escalation Detection")
    print("=" * 50)
    
    # Create tools
    read_tool, write_tool, admin_tool, processor_tool = create_sample_tools()
    
    # Create verifier with privilege escalation detection
    policy = CallStackPolicy(privilege_escalation_detection=True)
    verifier = CallStackVerifier(policy)
    
    session_id = "privilege_test"
    
    print("\n🛡️ Testing privilege escalation prevention:")
    try:
        # Normal call - should succeed
        verifier.verify_call(read_tool, session_id=session_id)
        print(f"   Call 1: {read_tool.id} - ✅ Allowed")
        
        # Try to escalate to admin tool - should be blocked
        result = verifier.verify_call(admin_tool, caller_tool=read_tool, session_id=session_id)
        print(f"   Call 2: {read_tool.id} -> {admin_tool.id} - {'✅ Allowed' if result else '❌ Blocked (Privilege Escalation)'}")
        
    except Exception as e:
        print(f"   Call 2: ❌ Blocked: {e}")


def demonstrate_call_chain_authorization():
    """Demonstrate explicit call chain authorization"""
    print("\n🔗 Call Chain Authorization")
    print("=" * 50)
    
    # Create tools
    read_tool, write_tool, admin_tool, processor_tool = create_sample_tools()
    
    # Create policy with explicit chain authorization
    policy = CallStackPolicy(
        require_explicit_chain_permission=True,
        allowed_call_chains={
            "file-reader": ["data-processor"],  # read_tool can call processor_tool
            "data-processor": ["file-writer"],  # processor_tool can call write_tool
        },
        blocked_call_chains={
            "file-reader": ["system-admin"],    # read_tool cannot call admin_tool
        }
    )
    verifier = CallStackVerifier(policy)
    
    session_id = "chain_test"
    
    print("\n🔐 Testing explicit chain authorization:")
    
    # Test allowed chain
    try:
        verifier.verify_call(read_tool, session_id=session_id)
        print(f"   Call 1: {read_tool.id} - ✅ Allowed")
        
        result = verifier.verify_call(processor_tool, caller_tool=read_tool, session_id=session_id)
        print(f"   Call 2: {read_tool.id} -> {processor_tool.id} - {'✅ Allowed' if result else '❌ Blocked'}")
        
        verifier.complete_call(processor_tool.id, session_id)
        verifier.complete_call(read_tool.id, session_id)
        
    except Exception as e:
        print(f"   ❌ Error in allowed chain: {e}")
    
    # Test blocked chain
    try:
        verifier.verify_call(read_tool, session_id=session_id)
        result = verifier.verify_call(admin_tool, caller_tool=read_tool, session_id=session_id)
        print(f"   Call 3: {read_tool.id} -> {admin_tool.id} - {'✅ Allowed' if result else '❌ Blocked (Unauthorized Chain)'}")
        
    except Exception as e:
        print(f"   Call 3: ❌ Blocked: {e}")


def demonstrate_statistics():
    """Demonstrate call stack statistics"""
    print("\n📊 Call Stack Statistics")
    print("=" * 50)
    
    # Create tools and verifier
    read_tool, write_tool, admin_tool, processor_tool = create_sample_tools()
    verifier = CallStackVerifier()
    
    # Make some calls to generate statistics
    session_id = "stats_test"
    
    try:
        verifier.verify_call(read_tool, session_id=session_id)
        verifier.verify_call(processor_tool, caller_tool=read_tool, session_id=session_id)
        verifier.complete_call(processor_tool.id, session_id)
        verifier.complete_call(read_tool.id, session_id)
        
        # Try some violations
        try:
            verifier.verify_call(admin_tool, caller_tool=read_tool, session_id=session_id)
        except:
            pass  # Expected to fail
        
    except Exception as e:
        pass  # Some calls may fail, that's expected
    
    # Get statistics
    stats = verifier.get_statistics()
    
    print("\n📈 Statistics:")
    print(f"   Total calls: {stats['total_calls']}")
    print(f"   Total violations: {stats['total_violations']}")
    print(f"   Violation rate: {stats['violation_rate']:.2%}")
    print(f"   Active sessions: {stats['active_sessions']}")
    print(f"   Max active depth: {stats['max_active_depth']}")
    
    if stats['violation_counts']:
        print("   Violation types:")
        for vtype, count in stats['violation_counts'].items():
            print(f"     - {vtype}: {count}")


def main():
    """Run all call stack verification demonstrations"""
    print("🚀 ETDI Call Stack Verification Examples")
    print("=" * 60)
    
    demonstrate_basic_verification()
    demonstrate_depth_limiting()
    demonstrate_circular_detection()
    demonstrate_privilege_escalation_detection()
    demonstrate_call_chain_authorization()
    demonstrate_statistics()
    
    print("\n" + "=" * 60)
    print("✅ Call stack verification examples completed!")
    print("\n💡 Key Benefits:")
    print("   • Prevents unauthorized tool chaining")
    print("   • Blocks privilege escalation attacks")
    print("   • Detects circular dependencies")
    print("   • Enforces call depth limits")
    print("   • Provides comprehensive audit trails")


if __name__ == "__main__":
    main()