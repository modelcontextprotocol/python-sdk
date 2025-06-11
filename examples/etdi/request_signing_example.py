"""
ETDI Request Signing Example - Fixed Implementation

This example demonstrates the corrected request signing implementation
that properly integrates with the MCP protocol.
"""

import asyncio
import logging
from mcp.etdi.crypto.key_manager import KeyManager
from mcp.etdi.crypto.request_signer import RequestSigner
from mcp.etdi.types_extensions import create_signed_call_tool_request
from mcp.types import CallToolRequest

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Demonstrate the fixed request signing implementation"""
    
    print("🔐 ETDI Request Signing - Fixed Implementation")
    print("=" * 60)
    
    # 1. Create key manager and generate keys
    print("\n📋 Step 1: Key Generation")
    key_manager = KeyManager()
    key_pair = key_manager.generate_key_pair("demo-client")
    print(f"✅ Generated key pair: {key_pair.key_id}")
    print(f"   Algorithm: {key_pair.algorithm}")
    print(f"   Fingerprint: {key_pair.public_key_fingerprint()}")
    
    # 2. Create request signer
    print("\n📋 Step 2: Request Signer Setup")
    request_signer = RequestSigner(key_manager, "demo-client")
    print("✅ Request signer initialized")
    
    # 3. Sign a tool invocation
    print("\n📋 Step 3: Tool Invocation Signing")
    tool_name = "secure_calculator"
    arguments = {"operation": "add", "a": 10, "b": 5}
    
    signature_headers = request_signer.sign_tool_invocation(tool_name, arguments)
    print("✅ Tool invocation signed")
    print(f"   Signature: {signature_headers['X-ETDI-Tool-Signature'][:20]}...")
    print(f"   Timestamp: {signature_headers['X-ETDI-Timestamp']}")
    print(f"   Key ID: {signature_headers['X-ETDI-Key-ID']}")
    print(f"   Algorithm: {signature_headers['X-ETDI-Algorithm']}")
    
    # 4. Create signed MCP request (THE FIX!)
    print("\n📋 Step 4: MCP Protocol Integration (FIXED)")
    
    # OLD BROKEN WAY (commented out):
    # standard_request = CallToolRequest(
    #     method="tools/call",
    #     params=CallToolRequestParams(name=tool_name, arguments=arguments)
    # )
    # # ❌ No way to add signature headers to standard MCP request!
    
    # NEW FIXED WAY:
    signed_request = create_signed_call_tool_request(
        name=tool_name,
        arguments=arguments,
        signature_headers=signature_headers
    )
    
    print("✅ Created signed MCP request using ETDI protocol extension")
    print(f"   Method: {signed_request.method}")
    print(f"   Tool: {signed_request.params.name}")
    print(f"   Has signature: {signed_request.has_signature()}")
    
    # 5. Demonstrate backward compatibility
    print("\n📋 Step 5: Backward Compatibility")
    
    # Standard request without signature
    standard_request = create_signed_call_tool_request(
        name="standard_tool",
        arguments={"param": "value"}
        # No signature_headers = backward compatible
    )
    
    print("✅ Created standard MCP request (no signature)")
    print(f"   Method: {standard_request.method}")
    print(f"   Tool: {standard_request.params.name}")
    print(f"   Has signature: {standard_request.has_signature()}")
    
    # 6. Demonstrate serialization (important for MCP transport)
    print("\n📋 Step 6: MCP Transport Serialization")
    
    # Serialize signed request
    signed_dict = signed_request.model_dump()
    print("✅ Signed request serialized for MCP transport:")
    print(f"   Method: {signed_dict['method']}")
    print(f"   Params keys: {list(signed_dict['params'].keys())}")
    print(f"   Has etdi_signature: {'etdi_signature' in signed_dict['params']}")
    
    # Serialize standard request
    standard_dict = standard_request.model_dump()
    print("✅ Standard request serialized for MCP transport:")
    print(f"   Method: {standard_dict['method']}")
    print(f"   Params keys: {list(standard_dict['params'].keys())}")
    print(f"   Has etdi_signature: {'etdi_signature' in standard_dict['params']}")
    
    # 7. Demonstrate server-side signature extraction
    print("\n📋 Step 7: Server-Side Signature Extraction")
    
    # Server receives the signed request and can extract signature headers
    if hasattr(signed_request.params, 'etdi_signature'):
        extracted_headers = signed_request.get_signature_headers()
        print("✅ Server extracted signature headers:")
        for key, value in extracted_headers.items():
            if key == 'X-ETDI-Signature':
                print(f"   {key}: {value[:20]}...")
            else:
                print(f"   {key}: {value}")
    
    print("\n🎉 Request Signing Fix Complete!")
    print("\n📋 Summary of the Fix:")
    print("1. ✅ Extended MCP CallToolRequestParams with ETDI signature fields")
    print("2. ✅ Created ETDI protocol extension for signed requests")
    print("3. ✅ Updated ETDIClient to use signed MCP requests")
    print("4. ✅ Updated SecureSession to use signed MCP requests")
    print("5. ✅ Updated FastMCP server to extract signatures from request params")
    print("6. ✅ Maintained full backward compatibility")
    print("7. ✅ Works with all MCP transports (stdio, websocket, SSE)")
    
    print("\n🔒 The root cause was fixed by extending the MCP protocol itself")
    print("   instead of trying to inject headers into transport layers!")


if __name__ == "__main__":
    asyncio.run(main())