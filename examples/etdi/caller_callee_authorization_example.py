#!/usr/bin/env python3
"""
ETDI Tool-Specific Caller/Callee Authorization Example

Demonstrates how tools can specify exactly which other tools are allowed
to call them (callers) and which tools they are allowed to call (callees).
This provides fine-grained, declarative security at the tool level.
"""

from mcp.etdi import (
    ETDIToolDefinition, 
    Permission, 
    CallStackConstraints,
    CallStackVerifier, 
    CallStackPolicy
)


def create_authorization_demo_tools():
    """Create a set of tools demonstrating caller/callee authorization"""
    
    # 1. Data Source Tool - Can be called by anyone, but can only call validators
    data_source = ETDIToolDefinition(
        id="data-source",
        name="Data Source",
        version="1.0.0",
        description="Provides raw data - open to all callers",
        provider={"id": "data", "name": "Data Provider"},
        schema={"type": "object", "properties": {"query": {"type": "string"}}},
        permissions=[
            Permission(name="read_data", description="Read data", scope="data:read", required=True)
        ],
        call_stack_constraints=CallStackConstraints(
            # No allowed_callers = anyone can call this tool
            allowed_callees=["data-validator", "schema-validator"],  # Can only call validators
            blocked_callees=["data-sink", "admin-tool"]  # Explicitly blocked from calling these
        )
    )
    
    # 2. Data Validator - Only specific tools can call it, can call processors
    data_validator = ETDIToolDefinition(
        id="data-validator",
        name="Data Validator", 
        version="1.0.0",
        description="Validates data - restricted callers",
        provider={"id": "validation", "name": "Validation Provider"},
        schema={"type": "object", "properties": {"data": {"type": "object"}}},
        permissions=[
            Permission(name="validate_data", description="Validate data", scope="data:validate", required=True)
        ],
        call_stack_constraints=CallStackConstraints(
            allowed_callers=["data-source", "data-processor"],  # Only these can call this tool
            allowed_callees=["data-processor", "error-logger"],  # Can call processors and loggers
            blocked_callers=["admin-tool", "external-api"]  # Explicitly blocked callers
        )
    )
    
    # 3. Data Processor - Moderate restrictions
    data_processor = ETDIToolDefinition(
        id="data-processor",
        name="Data Processor",
        version="1.0.0", 
        description="Processes validated data",
        provider={"id": "processing", "name": "Processing Provider"},
        schema={"type": "object", "properties": {"validated_data": {"type": "object"}}},
        permissions=[
            Permission(name="process_data", description="Process data", scope="data:process", required=True)
        ],
        call_stack_constraints=CallStackConstraints(
            allowed_callers=["data-validator"],  # Only validator can call this
            allowed_callees=["data-sink", "audit-logger"],  # Can call sink and audit
            blocked_callees=["admin-tool", "external-api"]  # Cannot call admin or external
        )
    )
    
    # 4. Data Sink - Very restrictive, final destination
    data_sink = ETDIToolDefinition(
        id="data-sink",
        name="Data Sink",
        version="1.0.0",
        description="Final data destination - highly restricted",
        provider={"id": "storage", "name": "Storage Provider"},
        schema={"type": "object", "properties": {"processed_data": {"type": "object"}}},
        permissions=[
            Permission(name="store_data", description="Store data", scope="data:store", required=True)
        ],
        call_stack_constraints=CallStackConstraints(
            allowed_callers=["data-processor"],  # Only processor can call this
            allowed_callees=[],  # Cannot call any other tools (terminal node)
            blocked_callers=["data-source", "admin-tool", "external-api"]  # Explicit blocks
        )
    )
    
    # 5. Admin Tool - Powerful but restricted from data flow
    admin_tool = ETDIToolDefinition(
        id="admin-tool",
        name="Administrative Tool",
        version="1.0.0",
        description="Administrative operations - blocked from data flow",
        provider={"id": "admin", "name": "Admin Provider"},
        schema={"type": "object", "properties": {"command": {"type": "string"}}},
        permissions=[
            Permission(name="admin_access", description="Admin access", scope="admin:*", required=True)
        ],
        call_stack_constraints=CallStackConstraints(
            # No caller restrictions - can be called by anyone
            allowed_callees=["audit-logger", "system-monitor"],  # Can only call monitoring tools
            blocked_callees=["data-source", "data-validator", "data-processor", "data-sink"]  # Blocked from data flow
        )
    )
    
    # 6. External API - Untrusted, heavily restricted
    external_api = ETDIToolDefinition(
        id="external-api",
        name="External API Client",
        version="1.0.0",
        description="External API access - untrusted",
        provider={"id": "external", "name": "External Provider"},
        schema={"type": "object", "properties": {"endpoint": {"type": "string"}}},
        permissions=[
            Permission(name="api_access", description="API access", scope="api:external", required=True)
        ],
        call_stack_constraints=CallStackConstraints(
            # No one should call this directly - it's untrusted
            blocked_callers=["data-validator", "data-processor", "data-sink"],
            allowed_callees=[],  # Cannot call anything - isolated
            blocked_callees=["data-source", "data-validator", "data-processor", "data-sink", "admin-tool"]
        )
    )
    
    # 7. Audit Logger - Can be called by many, calls nothing
    audit_logger = ETDIToolDefinition(
        id="audit-logger",
        name="Audit Logger",
        version="1.0.0",
        description="Logs audit events - widely accessible",
        provider={"id": "logging", "name": "Logging Provider"},
        schema={"type": "object", "properties": {"event": {"type": "string"}}},
        permissions=[
            Permission(name="log_audit", description="Log audit events", scope="audit:log", required=True)
        ],
        call_stack_constraints=CallStackConstraints(
            # Most tools can call this for logging
            allowed_callers=["data-processor", "admin-tool", "data-validator"],
            allowed_callees=[],  # Logging is terminal - calls nothing
        )
    )
    
    return [data_source, data_validator, data_processor, data_sink, admin_tool, external_api, audit_logger]


def demonstrate_caller_authorization():
    """Demonstrate how caller authorization works"""
    print("👥 Caller Authorization Examples")
    print("=" * 60)
    
    tools = create_authorization_demo_tools()
    tool_map = {tool.id: tool for tool in tools}
    
    # Create verifier that respects tool constraints
    verifier = create_constraint_aware_verifier(tools)
    
    print("\n🔍 Testing Caller Authorization Rules:")
    
    # Test cases: [caller_id, callee_id, expected_result, reason]
    test_cases = [
        ("data-source", "data-validator", True, "data-source is in data-validator's allowed_callers"),
        ("admin-tool", "data-validator", False, "admin-tool is in data-validator's blocked_callers"),
        ("external-api", "data-validator", False, "external-api is in data-validator's blocked_callers"),
        ("data-processor", "data-validator", True, "data-processor is in data-validator's allowed_callers"),
        ("data-validator", "data-processor", True, "data-validator is in data-processor's allowed_callers"),
        ("data-source", "data-processor", False, "data-source is NOT in data-processor's allowed_callers"),
        ("data-processor", "data-sink", True, "data-processor is in data-sink's allowed_callers"),
        ("data-source", "data-sink", False, "data-source is in data-sink's blocked_callers"),
    ]
    
    for caller_id, callee_id, expected, reason in test_cases:
        caller_tool = tool_map[caller_id]
        callee_tool = tool_map[callee_id]
        
        try:
            session_id = f"test_{caller_id}_{callee_id}"
            verifier.verify_call(caller_tool, session_id=session_id)  # Start caller
            result = verifier.verify_call(callee_tool, caller_tool=caller_tool, session_id=session_id)
            
            status = "✅ ALLOWED" if result else "❌ BLOCKED"
            expected_status = "✅ ALLOWED" if expected else "❌ BLOCKED"
            match = "✓" if (result == expected) else "✗ MISMATCH"
            
            print(f"   {match} {caller_id} → {callee_id}: {status} (Expected: {expected_status})")
            print(f"      Reason: {reason}")
            
            verifier.clear_session(session_id)
            
        except Exception as e:
            status = "❌ BLOCKED"
            expected_status = "✅ ALLOWED" if expected else "❌ BLOCKED"
            match = "✓" if (not expected) else "✗ MISMATCH"
            
            print(f"   {match} {caller_id} → {callee_id}: {status} (Expected: {expected_status})")
            print(f"      Reason: {reason}")
            print(f"      Error: {str(e)[:80]}...")


def demonstrate_callee_authorization():
    """Demonstrate how callee authorization works"""
    print("\n📞 Callee Authorization Examples")
    print("=" * 60)
    
    tools = create_authorization_demo_tools()
    tool_map = {tool.id: tool for tool in tools}
    
    verifier = create_constraint_aware_verifier(tools)
    
    print("\n🔍 Testing Callee Authorization Rules:")
    
    # Test cases: [caller_id, callee_id, expected_result, reason]
    test_cases = [
        ("data-source", "data-validator", True, "data-validator is in data-source's allowed_callees"),
        ("data-source", "data-sink", False, "data-sink is in data-source's blocked_callees"),
        ("data-source", "admin-tool", False, "admin-tool is in data-source's blocked_callees"),
        ("data-validator", "data-processor", True, "data-processor is in data-validator's allowed_callees"),
        ("data-validator", "external-api", False, "external-api is NOT in data-validator's allowed_callees"),
        ("data-processor", "data-sink", True, "data-sink is in data-processor's allowed_callees"),
        ("data-processor", "admin-tool", False, "admin-tool is in data-processor's blocked_callees"),
        ("admin-tool", "audit-logger", True, "audit-logger is in admin-tool's allowed_callees"),
        ("admin-tool", "data-source", False, "data-source is in admin-tool's blocked_callees"),
        ("external-api", "data-source", False, "data-source is in external-api's blocked_callees"),
    ]
    
    for caller_id, callee_id, expected, reason in test_cases:
        caller_tool = tool_map[caller_id]
        callee_tool = tool_map[callee_id]
        
        try:
            session_id = f"test_{caller_id}_{callee_id}"
            verifier.verify_call(caller_tool, session_id=session_id)  # Start caller
            result = verifier.verify_call(callee_tool, caller_tool=caller_tool, session_id=session_id)
            
            status = "✅ ALLOWED" if result else "❌ BLOCKED"
            expected_status = "✅ ALLOWED" if expected else "❌ BLOCKED"
            match = "✓" if (result == expected) else "✗ MISMATCH"
            
            print(f"   {match} {caller_id} → {callee_id}: {status} (Expected: {expected_status})")
            print(f"      Reason: {reason}")
            
            verifier.clear_session(session_id)
            
        except Exception as e:
            status = "❌ BLOCKED"
            expected_status = "✅ ALLOWED" if expected else "❌ BLOCKED"
            match = "✓" if (not expected) else "✗ MISMATCH"
            
            print(f"   {match} {caller_id} → {callee_id}: {status} (Expected: {expected_status})")
            print(f"      Reason: {reason}")
            print(f"      Error: {str(e)[:80]}...")


def demonstrate_valid_call_chains():
    """Demonstrate valid call chains that respect all constraints"""
    print("\n🔗 Valid Call Chain Examples")
    print("=" * 60)
    
    tools = create_authorization_demo_tools()
    tool_map = {tool.id: tool for tool in tools}
    
    verifier = create_constraint_aware_verifier(tools)
    
    print("\n✅ Testing Valid Call Chains:")
    
    # Valid chain: data-source → data-validator → data-processor → data-sink
    print("\n1. Complete Data Processing Chain:")
    session_id = "valid_chain_1"
    
    try:
        # Step 1: data-source
        verifier.verify_call(tool_map["data-source"], session_id=session_id)
        print("   ✅ data-source (root call)")
        
        # Step 2: data-source → data-validator
        verifier.verify_call(tool_map["data-validator"], caller_tool=tool_map["data-source"], session_id=session_id)
        print("   ✅ data-source → data-validator")
        
        # Step 3: data-validator → data-processor
        verifier.verify_call(tool_map["data-processor"], caller_tool=tool_map["data-validator"], session_id=session_id)
        print("   ✅ data-validator → data-processor")
        
        # Step 4: data-processor → data-sink
        verifier.verify_call(tool_map["data-sink"], caller_tool=tool_map["data-processor"], session_id=session_id)
        print("   ✅ data-processor → data-sink")
        
        print("   🎉 Complete chain successful!")
        
    except Exception as e:
        print(f"   ❌ Chain failed: {e}")
    
    verifier.clear_session(session_id)
    
    # Valid chain: admin-tool → audit-logger
    print("\n2. Admin Audit Chain:")
    session_id = "valid_chain_2"
    
    try:
        # Step 1: admin-tool
        verifier.verify_call(tool_map["admin-tool"], session_id=session_id)
        print("   ✅ admin-tool (root call)")
        
        # Step 2: admin-tool → audit-logger
        verifier.verify_call(tool_map["audit-logger"], caller_tool=tool_map["admin-tool"], session_id=session_id)
        print("   ✅ admin-tool → audit-logger")
        
        print("   🎉 Admin audit chain successful!")
        
    except Exception as e:
        print(f"   ❌ Chain failed: {e}")
    
    verifier.clear_session(session_id)


def demonstrate_blocked_call_chains():
    """Demonstrate call chains that are blocked by constraints"""
    print("\n🚫 Blocked Call Chain Examples")
    print("=" * 60)
    
    tools = create_authorization_demo_tools()
    tool_map = {tool.id: tool for tool in tools}
    
    verifier = create_constraint_aware_verifier(tools)
    
    print("\n❌ Testing Blocked Call Chains:")
    
    # Blocked chain: admin-tool → data-source (admin blocked from data flow)
    print("\n1. Admin Trying to Access Data Flow:")
    session_id = "blocked_chain_1"
    
    try:
        verifier.verify_call(tool_map["admin-tool"], session_id=session_id)
        print("   ✅ admin-tool (root call)")
        
        verifier.verify_call(tool_map["data-source"], caller_tool=tool_map["admin-tool"], session_id=session_id)
        print("   ❌ This should not succeed!")
        
    except Exception as e:
        print(f"   ✅ Correctly blocked: admin-tool → data-source")
        print(f"      Reason: {str(e)[:80]}...")
    
    verifier.clear_session(session_id)
    
    # Blocked chain: external-api → data-validator (external blocked from data)
    print("\n2. External API Trying to Access Data:")
    session_id = "blocked_chain_2"
    
    try:
        verifier.verify_call(tool_map["external-api"], session_id=session_id)
        print("   ✅ external-api (root call)")
        
        verifier.verify_call(tool_map["data-validator"], caller_tool=tool_map["external-api"], session_id=session_id)
        print("   ❌ This should not succeed!")
        
    except Exception as e:
        print(f"   ✅ Correctly blocked: external-api → data-validator")
        print(f"      Reason: {str(e)[:80]}...")
    
    verifier.clear_session(session_id)
    
    # Blocked chain: data-source → data-sink (skipping validation/processing)
    print("\n3. Data Source Trying to Skip Processing:")
    session_id = "blocked_chain_3"
    
    try:
        verifier.verify_call(tool_map["data-source"], session_id=session_id)
        print("   ✅ data-source (root call)")
        
        verifier.verify_call(tool_map["data-sink"], caller_tool=tool_map["data-source"], session_id=session_id)
        print("   ❌ This should not succeed!")
        
    except Exception as e:
        print(f"   ✅ Correctly blocked: data-source → data-sink")
        print(f"      Reason: {str(e)[:80]}...")
    
    verifier.clear_session(session_id)


def create_constraint_aware_verifier(tools):
    """Create a verifier that uses tool-specific constraints"""
    policy = CallStackPolicy(
        max_call_depth=10,
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


def print_authorization_matrix():
    """Print a visual matrix of caller/callee authorizations"""
    print("\n📊 Authorization Matrix")
    print("=" * 60)
    
    tools = create_authorization_demo_tools()
    tool_ids = [tool.id for tool in tools]
    
    print("\nCaller/Callee Authorization Matrix:")
    print("✅ = Allowed, ❌ = Blocked, ⚪ = Not specified")
    print()
    
    # Header
    print("Caller \\ Callee".ljust(20), end="")
    for callee_id in tool_ids:
        print(callee_id[:8].ljust(10), end="")
    print()
    
    print("-" * (20 + len(tool_ids) * 10))
    
    # Matrix
    for caller_tool in tools:
        print(caller_tool.id[:18].ljust(20), end="")
        
        for callee_tool in tools:
            if caller_tool.id == callee_tool.id:
                print("⚫".ljust(10), end="")  # Self-call
                continue
                
            # Check caller constraints (what this tool can call)
            caller_constraints = caller_tool.call_stack_constraints
            callee_constraints = callee_tool.call_stack_constraints
            
            allowed = True
            
            # Check caller's allowed_callees
            if caller_constraints and caller_constraints.allowed_callees is not None:
                if callee_tool.id not in caller_constraints.allowed_callees:
                    allowed = False
            
            # Check caller's blocked_callees
            if caller_constraints and caller_constraints.blocked_callees:
                if callee_tool.id in caller_constraints.blocked_callees:
                    allowed = False
            
            # Check callee's allowed_callers
            if callee_constraints and callee_constraints.allowed_callers is not None:
                if caller_tool.id not in callee_constraints.allowed_callers:
                    allowed = False
            
            # Check callee's blocked_callers
            if callee_constraints and callee_constraints.blocked_callers:
                if caller_tool.id in callee_constraints.blocked_callers:
                    allowed = False
            
            symbol = "✅" if allowed else "❌"
            print(symbol.ljust(10), end="")
        
        print()


def main():
    """Run caller/callee authorization demonstrations"""
    print("🔐 ETDI Tool-Specific Caller/Callee Authorization")
    print("=" * 70)
    
    print("\n💡 How It Works:")
    print("   • Each tool defines allowed_callers (who can call it)")
    print("   • Each tool defines allowed_callees (who it can call)")
    print("   • Each tool defines blocked_callers/callees (explicit denials)")
    print("   • Verification checks BOTH caller and callee constraints")
    print("   • Provides fine-grained, declarative security")
    
    demonstrate_caller_authorization()
    demonstrate_callee_authorization()
    demonstrate_valid_call_chains()
    demonstrate_blocked_call_chains()
    print_authorization_matrix()
    
    print("\n" + "=" * 70)
    print("✅ Caller/Callee authorization examples completed!")
    print("\n🔑 Key Benefits:")
    print("   • Tool-level security: Each tool controls its interactions")
    print("   • Bidirectional checks: Both caller and callee must agree")
    print("   • Explicit denials: Blocked lists override allowed lists")
    print("   • Zero-trust: Default deny unless explicitly allowed")
    print("   • Protocol-native: Constraints travel with tool definitions")
    print("   • Audit-friendly: Clear authorization rules and violations")


if __name__ == "__main__":
    main()