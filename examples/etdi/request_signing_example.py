"""
Example demonstrating ETDI request-level signing with key exchange
"""

import asyncio
import logging
from datetime import datetime
from mcp.etdi.crypto import KeyManager, RequestSigner, SignatureVerifier, KeyExchangeManager
from mcp.etdi.crypto.key_exchange import KeyExchangeProtocol

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def demo_key_management():
    """Demonstrate key generation and management"""
    print("🔑 Key Management Demo")
    print("=" * 50)
    
    # Initialize key manager
    key_manager = KeyManager()
    
    # Generate key pairs for client and server
    client_key = key_manager.generate_key_pair("etdi-client", expires_in_days=365)
    server_key = key_manager.generate_key_pair("etdi-server", expires_in_days=365)
    
    print(f"✅ Generated client key: {client_key.key_id}")
    print(f"   Fingerprint: {client_key.public_key_fingerprint()}")
    print(f"   Created: {client_key.created_at}")
    print(f"   Expires: {client_key.expires_at}")
    
    print(f"✅ Generated server key: {server_key.key_id}")
    print(f"   Fingerprint: {server_key.public_key_fingerprint()}")
    
    # List all keys
    keys_info = key_manager.list_keys()
    print(f"\n📋 Available keys: {len(keys_info)}")
    for key_id, info in keys_info.items():
        print(f"  - {key_id}: {info['status']} (fingerprint: {info['fingerprint']})")
    
    # Export public key for sharing
    client_public_pem = key_manager.export_public_key("etdi-client")
    print(f"\n📤 Client public key (first 100 chars):")
    print(f"   {client_public_pem[:100]}...")
    
    return key_manager


async def demo_request_signing():
    """Demonstrate HTTP request signing"""
    print("\n🖊️  Request Signing Demo")
    print("=" * 50)
    
    # Initialize components
    key_manager = KeyManager()
    client_key = key_manager.get_or_create_key_pair("etdi-client")
    
    # Create request signer
    signer = RequestSigner(key_manager, "etdi-client")
    
    # Example HTTP request
    method = "POST"
    url = "https://api.example.com/mcp/tools/call"
    headers = {
        "Content-Type": "application/json",
        "Host": "api.example.com"
    }
    body = '{"tool_id": "calculator", "parameters": {"operation": "add", "a": 5, "b": 3}}'
    
    # Sign the request
    signature_headers = signer.sign_request(method, url, headers, body)
    
    print(f"📝 Original request:")
    print(f"   {method} {url}")
    print(f"   Headers: {headers}")
    print(f"   Body: {body}")
    
    print(f"\n🔐 Signature headers:")
    for key, value in signature_headers.items():
        print(f"   {key}: {value}")
    
    # Combine headers for verification
    all_headers = {**headers, **signature_headers}
    
    # Verify the signature
    verifier = SignatureVerifier(key_manager)
    is_valid, error = verifier.verify_request_signature(method, url, all_headers, body)
    
    print(f"\n✅ Signature verification: {'VALID' if is_valid else 'INVALID'}")
    if error:
        print(f"   Error: {error}")
    
    return signer, verifier


async def demo_tool_invocation_signing():
    """Demonstrate tool invocation signing"""
    print("\n🔧 Tool Invocation Signing Demo")
    print("=" * 50)
    
    key_manager = KeyManager()
    signer = RequestSigner(key_manager, "etdi-client")
    verifier = SignatureVerifier(key_manager)
    
    # Tool invocation parameters
    tool_id = "secure_calculator"
    parameters = {
        "operation": "multiply",
        "a": 7,
        "b": 6
    }
    
    # Sign the tool invocation
    signature_headers = signer.sign_tool_invocation(tool_id, parameters)
    
    print(f"🔧 Tool invocation:")
    print(f"   Tool ID: {tool_id}")
    print(f"   Parameters: {parameters}")
    
    print(f"\n🔐 Invocation signature:")
    for key, value in signature_headers.items():
        print(f"   {key}: {value}")
    
    # Verify the signature
    is_valid, error = verifier.verify_tool_invocation_signature(
        tool_id, parameters, signature_headers
    )
    
    print(f"\n✅ Invocation signature verification: {'VALID' if is_valid else 'INVALID'}")
    if error:
        print(f"   Error: {error}")


async def demo_key_exchange():
    """Demonstrate key exchange between client and server"""
    print("\n🤝 Key Exchange Demo")
    print("=" * 50)
    
    # Initialize key managers for client and server
    client_key_manager = KeyManager("~/.etdi/keys/client")
    server_key_manager = KeyManager("~/.etdi/keys/server")
    
    # Initialize key exchange managers
    client_exchange = KeyExchangeManager(client_key_manager, "etdi-client-001")
    server_exchange = KeyExchangeManager(server_key_manager, "etdi-server-001")
    
    print("🔄 Step 1: Client initiates key exchange")
    
    # Client initiates key exchange
    exchange_request = await client_exchange.initiate_key_exchange(
        target_entity_id="etdi-server-001",
        protocol=KeyExchangeProtocol.SIMPLE_EXCHANGE
    )
    
    print(f"   Request ID: {exchange_request.nonce}")
    print(f"   Client key ID: {exchange_request.requester_public_key.key_id}")
    print(f"   Client fingerprint: {exchange_request.requester_public_key.fingerprint}")
    
    print("\n🔄 Step 2: Server handles key exchange request")
    
    # Server handles the request
    exchange_response = await server_exchange.handle_key_exchange_request(
        exchange_request, auto_accept=True
    )
    
    print(f"   Response accepted: {exchange_response.accepted}")
    if exchange_response.accepted:
        print(f"   Server key ID: {exchange_response.responder_public_key.key_id}")
        print(f"   Server fingerprint: {exchange_response.responder_public_key.fingerprint}")
    else:
        print(f"   Error: {exchange_response.error_message}")
    
    print("\n🔄 Step 3: Client handles key exchange response")
    
    # Client handles the response
    success = await client_exchange.handle_key_exchange_response(exchange_response)
    print(f"   Exchange completed: {success}")
    
    if success:
        # Show trusted keys
        client_trusted = client_exchange.get_trusted_keys()
        server_trusted = server_exchange.get_trusted_keys()
        
        print(f"\n📋 Client trusted keys: {len(client_trusted)}")
        for entity_id, key_info in client_trusted.items():
            print(f"   - {entity_id}: {key_info.fingerprint}")
        
        print(f"\n📋 Server trusted keys: {len(server_trusted)}")
        for entity_id, key_info in server_trusted.items():
            print(f"   - {entity_id}: {key_info.fingerprint}")
    
    return client_exchange, server_exchange


async def demo_end_to_end_signing():
    """Demonstrate end-to-end request signing with key exchange"""
    print("\n🌐 End-to-End Signing Demo")
    print("=" * 50)
    
    # Set up key exchange
    client_exchange, server_exchange = await demo_key_exchange()
    
    # Get key managers
    client_key_manager = client_exchange.key_manager
    server_key_manager = server_exchange.key_manager
    
    # Create signers
    client_signer = RequestSigner(client_key_manager, "etdi-client-001")
    server_verifier = SignatureVerifier(server_key_manager)
    
    # Add client's public key to server's verifier
    client_key_info = client_exchange.get_trusted_keys().get("etdi-server-001")
    if client_key_info:
        # Actually, we need the server to trust the client's key
        server_trusted_client = server_exchange.get_trusted_keys().get("etdi-client-001")
        if server_trusted_client:
            server_verifier.add_trusted_public_key(
                "etdi-client-001", 
                server_trusted_client.public_key_pem
            )
    
    print("🔐 Client signs request with exchanged keys")
    
    # Client signs a request
    method = "POST"
    url = "https://secure-server.example.com/mcp/tools/call"
    headers = {"Content-Type": "application/json"}
    body = '{"tool_id": "secure_file_reader", "parameters": {"filename": "secret.txt"}}'
    
    signature_headers = client_signer.sign_request(method, url, headers, body)
    all_headers = {**headers, **signature_headers}
    
    print(f"   Signed request to: {url}")
    print(f"   Signature: {signature_headers['X-ETDI-Signature'][:32]}...")
    
    print("\n🔍 Server verifies request signature")
    
    # Server verifies the signature
    is_valid, error = server_verifier.verify_request_signature(
        method, url, all_headers, body
    )
    
    print(f"   Verification result: {'✅ VALID' if is_valid else '❌ INVALID'}")
    if error:
        print(f"   Error: {error}")
    
    if is_valid:
        print("   🎉 Request authenticated! Tool invocation can proceed.")
    else:
        print("   🚫 Request rejected! Tool invocation blocked.")


async def main():
    """Run all demos"""
    print("🔐 ETDI Request Signing & Key Exchange Demo")
    print("=" * 60)
    
    try:
        # Run demos in sequence
        await demo_key_management()
        await demo_request_signing()
        await demo_tool_invocation_signing()
        await demo_end_to_end_signing()
        
        print("\n✅ All demos completed successfully!")
        
        print("\n💡 Integration Points:")
        print("1. Add request signing to ETDIClient for all MCP requests")
        print("2. Add signature verification to ETDISecureServer middleware")
        print("3. Implement key exchange during client-server handshake")
        print("4. Store trusted keys in approval manager for persistence")
        print("5. Add CLI commands for key management and exchange")
        
    except Exception as e:
        logger.error(f"Demo failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())