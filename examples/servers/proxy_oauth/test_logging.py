#!/usr/bin/env python3
"""
Test script to demonstrate the enhanced logging features of the transparent OAuth proxy.
This script makes requests to various endpoints to show the comprehensive logging.
"""

import time
import requests
import json
import sys
from threading import Thread
import subprocess
import os
import signal

def test_endpoints():
    """Test various endpoints to demonstrate logging."""
    base_url = "http://localhost:8000"
    
    print("\n" + "="*60)
    print("🧪 TESTING ENHANCED LOGGING FEATURES")
    print("="*60)
    
    # Wait for server to be ready
    print("⏳ Waiting for server to be ready...")
    time.sleep(3)
    
    try:
        # Test 1: Metadata discovery
        print("\n🔍 Testing OAuth metadata discovery...")
        response = requests.get(f"{base_url}/.well-known/oauth-authorization-server", 
                              headers={"Host": "localhost:8000"})
        print(f"   Status: {response.status_code}")
        
        # Test 2: Client registration (DCR)
        print("\n📝 Testing Dynamic Client Registration...")
        registration_data = {
            "redirect_uris": ["http://localhost:3000/callback"],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "client_name": "Test MCP Client"
        }
        response = requests.post(f"{base_url}/register", 
                               json=registration_data,
                               headers={"Content-Type": "application/json"})
        print(f"   Status: {response.status_code}")
        
        # Test 3: Authorization endpoint
        print("\n🔐 Testing authorization endpoint...")
        auth_params = {
            "response_type": "code",
            "client_id": "test-client-id", 
            "redirect_uri": "http://localhost:3000/callback",
            "scope": "openid profile email",
            "state": "test-state-12345",
            "code_challenge": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
            "code_challenge_method": "S256"
        }
        response = requests.get(f"{base_url}/authorize", 
                              params=auth_params,
                              allow_redirects=False)
        print(f"   Status: {response.status_code}")
        
        # Test 4: Token endpoint (this will show the most comprehensive logging)
        print("\n🎫 Testing token endpoint (will fail but show logging)...")
        token_data = {
            "grant_type": "authorization_code",
            "client_id": "test-client-id",
            "client_secret": "test-client-secret", 
            "code": "test_auth_code_abcdef123456",
            "redirect_uri": "http://localhost:3000/callback",
            "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        }
        response = requests.post(f"{base_url}/token",
                               data=token_data,
                               headers={"Content-Type": "application/x-www-form-urlencoded"})
        print(f"   Status: {response.status_code}")
        
        # Test 5: Another token request with different parameters
        print("\n🎫 Testing token endpoint with different parameters...")
        token_data2 = {
            "grant_type": "authorization_code",
            "client_id": "test-client-id",
            "code": "different_test_code_xyz789",
            "redirect_uri": "http://localhost:3000/callback"
        }
        response = requests.post(f"{base_url}/token",
                               data=token_data2,
                               headers={"Content-Type": "application/x-www-form-urlencoded"})
        print(f"   Status: {response.status_code}")
        
        print("\n✅ Test requests completed!")
        print("🔍 Check the server logs above to see the enhanced logging with:")
        print("   • Correlation IDs for request tracing")
        print("   • Detailed request/response headers and data")
        print("   • Timing information")
        print("   • Emoji indicators for easy scanning")
        print("   • Sensitive data redaction")
        
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to server. Make sure it's running on port 8000.")
    except Exception as e:
        print(f"❌ Error during testing: {e}")

if __name__ == "__main__":
    test_endpoints() 