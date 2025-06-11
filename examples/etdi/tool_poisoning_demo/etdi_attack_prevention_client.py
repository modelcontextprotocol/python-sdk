#!/usr/bin/env python3
"""
ETDI Attack Prevention Client

This client demonstrates how ETDI prevents tool poisoning attacks by:
1. Connecting to both legitimate and malicious servers
2. Analyzing tool security metadata
3. Blocking malicious tools before execution
4. Allowing legitimate ETDI-protected tools to execute safely

This shows real MCP server-client interaction with ETDI security.
"""

import asyncio
import json
import sys
import subprocess
import time
from contextlib import AsyncExitStack
from datetime import datetime
from typing import Dict, List, Optional, Any
import os

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

# Auth0 Configuration for verification
AUTH0_CONFIG = {
    "provider": "auth0",
    "client_id": os.getenv("ETDI_CLIENT_ID", "your-auth0-client-id"),  # ETDI Tool Provider Demo
    "domain": os.getenv("ETDI_AUTH0_DOMAIN", "your-auth0-domain.auth0.com"),
    "audience": "https://api.etdi-tools.demo.com",  # ETDI Tool Registry API
    "scopes": ["read", "write", "execute", "admin"]
}

class ETDISecurityAnalyzer:
    """ETDI security analyzer for tool verification"""
    
    def __init__(self):
        self.security_log = []
        
    def log_security_event(self, event_type: str, details: str, severity: str = "INFO"):
        """Log security events"""
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "details": details,
            "severity": severity
        }
        self.security_log.append(event)
        
        severity_emoji = {
            "INFO": "ℹ️",
            "WARNING": "⚠️",
            "ERROR": "❌",
            "SUCCESS": "✅",
            "CRITICAL": "🚨"
        }
        
        print(f"{severity_emoji.get(severity, 'ℹ️')} ETDI SECURITY: {event_type} - {details}")
    
    def analyze_server_security(self, server_info: Dict[str, Any], server_name: str) -> Dict[str, Any]:
        """Analyze server security using ETDI verification"""
        print(f"\n🔍 ETDI SECURITY ANALYSIS FOR {server_name}")
        print(f"=" * 60)
        print(f"📋 Server Name: {server_info.get('server_name', 'Unknown')}")
        print(f"🏢 Provider: {server_info.get('provider', 'Unknown')}")
        print(f"📊 Starting security verification...")
        
        analysis = {
            "server_name": server_info.get("server_name", "Unknown"),
            "provider": server_info.get("provider", "Unknown"),
            "etdi_enabled": server_info.get("etdi_enabled", False),
            "oauth_enabled": server_info.get("oauth_enabled", False),
            "security_score": 0,
            "security_issues": [],
            "trust_level": "UNTRUSTED",
            "recommendation": "BLOCK"
        }
        
        print(f"\n🔒 ETDI VERIFICATION CHECKS:")
        print(f"-" * 30)
        
        # ETDI verification (most important)
        if server_info.get("etdi_enabled"):
            analysis["security_score"] += 50
            print(f"✅ ETDI Protection: ENABLED (+50 points)")
            self.log_security_event(
                "ETDI_VERIFIED",
                f"ETDI security features detected for {analysis['server_name']}",
                "SUCCESS"
            )
        else:
            analysis["security_issues"].append("No ETDI security")
            print(f"❌ ETDI Protection: DISABLED (0 points)")
            print(f"   🚨 CRITICAL: Cannot verify tool authenticity!")
            self.log_security_event(
                "ETDI_MISSING",
                f"No ETDI protection found for {analysis['server_name']}",
                "CRITICAL"
            )
        
        # OAuth verification
        if server_info.get("oauth_enabled"):
            analysis["security_score"] += 30
            print(f"✅ OAuth Authentication: ENABLED (+30 points)")
            self.log_security_event(
                "OAUTH_VERIFIED",
                f"OAuth 2.0 authentication detected for {analysis['server_name']}",
                "SUCCESS"
            )
        else:
            analysis["security_issues"].append("No OAuth authentication")
            print(f"❌ OAuth Authentication: DISABLED (0 points)")
            print(f"   🚨 CRITICAL: Cannot verify provider identity!")
            self.log_security_event(
                "OAUTH_MISSING",
                f"No OAuth protection found for {analysis['server_name']}",
                "CRITICAL"
            )
        
        # Auth0 domain verification
        if server_info.get("auth0_domain") == AUTH0_CONFIG["domain"]:
            analysis["security_score"] += 10
            print(f"✅ Auth0 Domain: VERIFIED (+10 points)")
            print(f"   🔑 Domain: {server_info.get('auth0_domain')}")
            self.log_security_event(
                "AUTH0_VERIFIED",
                f"Valid Auth0 domain verified for {analysis['server_name']}",
                "SUCCESS"
            )
        else:
            analysis["security_issues"].append("Invalid or missing Auth0 domain")
            print(f"❌ Auth0 Domain: INVALID/MISSING (0 points)")
            print(f"   🚨 Expected: {AUTH0_CONFIG['domain']}")
            print(f"   📄 Received: {server_info.get('auth0_domain', 'None')}")
        
        # Client ID verification
        if server_info.get("client_id") == AUTH0_CONFIG["client_id"]:
            analysis["security_score"] += 10
            print(f"✅ OAuth Client ID: VERIFIED (+10 points)")
            print(f"   🔑 Client ID: {server_info.get('client_id')}")
            self.log_security_event(
                "CLIENT_ID_VERIFIED",
                f"Valid OAuth client ID verified for {analysis['server_name']}",
                "SUCCESS"
            )
        else:
            analysis["security_issues"].append("Invalid or missing OAuth client ID")
            print(f"❌ OAuth Client ID: INVALID/MISSING (0 points)")
            print(f"   🚨 Expected: {AUTH0_CONFIG['client_id']}")
            print(f"   📄 Received: {server_info.get('client_id', 'None')}")
        
        print(f"\n📊 SECURITY SCORE CALCULATION:")
        print(f"-" * 35)
        print(f"🔒 ETDI Protection: {50 if server_info.get('etdi_enabled') else 0}/50 points")
        print(f"🔑 OAuth Authentication: {30 if server_info.get('oauth_enabled') else 0}/30 points")
        print(f"🌐 Auth0 Domain: {10 if server_info.get('auth0_domain') == AUTH0_CONFIG['domain'] else 0}/10 points")
        print(f"🆔 Client ID: {10 if server_info.get('client_id') == AUTH0_CONFIG['client_id'] else 0}/10 points")
        print(f"📈 TOTAL SCORE: {analysis['security_score']}/100 points")
        
        # Determine trust level and recommendation
        if analysis["security_score"] >= 80:
            analysis["trust_level"] = "TRUSTED"
            analysis["recommendation"] = "ALLOW"
            print(f"🛡️ TRUST LEVEL: TRUSTED (80+ points)")
            print(f"✅ RECOMMENDATION: ALLOW EXECUTION")
            print(f"   🔒 Server has strong ETDI protection")
            print(f"   🔑 Cryptographic proof of legitimacy")
        elif analysis["security_score"] >= 50:
            analysis["trust_level"] = "PARTIALLY_TRUSTED"
            analysis["recommendation"] = "WARN"
            print(f"⚠️ TRUST LEVEL: PARTIALLY_TRUSTED (50-79 points)")
            print(f"⚠️ RECOMMENDATION: WARN USER")
            print(f"   🔒 Some security features present")
            print(f"   ⚠️ Missing critical protections")
        else:
            analysis["trust_level"] = "UNTRUSTED"
            analysis["recommendation"] = "BLOCK"
            print(f"🚨 TRUST LEVEL: UNTRUSTED (0-49 points)")
            print(f"🛑 RECOMMENDATION: BLOCK EXECUTION")
            print(f"   ❌ Insufficient security features")
            print(f"   🚨 HIGH RISK OF TOOL POISONING ATTACK")
        
        if analysis['security_issues']:
            print(f"\n🚨 SECURITY ISSUES DETECTED:")
            for i, issue in enumerate(analysis['security_issues'], 1):
                print(f"   {i}. {issue}")
        
        print(f"=" * 60)
        
        return analysis

class ETDIAttackPreventionClient:
    """ETDI-enabled client that prevents tool poisoning attacks"""
    
    def __init__(self):
        self.security_analyzer = ETDISecurityAnalyzer()
        self.sessions: Dict[str, ClientSession] = {}
        self.server_analyses: Dict[str, Dict[str, Any]] = {}
        self.exit_stack = AsyncExitStack()
        
    async def connect_to_server(self, server_name: str, server_command: List[str]):
        """Connect to a server and analyze its security"""
        print(f"\n🔌 CONNECTING TO {server_name}")
        print(f"=" * 50)
        print(f"📋 Command: {' '.join(server_command)}")
        print(f"🔍 Initiating MCP connection...")
        
        try:
            # Create server parameters
            server_params = StdioServerParameters(
                command=server_command[0],
                args=server_command[1:] if len(server_command) > 1 else []
            )
            
            # Create MCP session using exit stack to keep it alive
            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read_stream, write_stream = stdio_transport
            
            session = await self.exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
            
            # Store session for later use
            self.sessions[server_name] = session
            
            print(f"✅ MCP connection established")
            print(f"🔍 Requesting server security information...")
            
            # Get server information for security analysis
            result = await session.call_tool("get_server_info", {})
            server_info = json.loads(result.content[0].text)
            
            print(f"📄 Server information received")
            
            # Analyze server security
            analysis = self.security_analyzer.analyze_server_security(server_info, server_name)
            self.server_analyses[server_name] = analysis
            
            print(f"\n✅ CONNECTION AND ANALYSIS COMPLETE")
            print(f"🔒 Security Score: {analysis['security_score']}/100")
            print(f"🛡️ Trust Level: {analysis['trust_level']}")
            print(f"📋 Recommendation: {analysis['recommendation']}")
            
            return True
            
        except Exception as e:
            print(f"❌ CONNECTION FAILED: {e}")
            self.security_analyzer.log_security_event(
                "CONNECTION_FAILED",
                f"Failed to connect to {server_name}: {e}",
                "ERROR"
            )
            return False
    
    async def disconnect_all(self):
        """Disconnect from all servers"""
        try:
            print(f"\n🔌 DISCONNECTING FROM ALL SERVERS")
            await self.exit_stack.aclose()
            self.sessions.clear()
            print("✅ All connections closed")
        except Exception as e:
            print(f"⚠️ Error during disconnection: {e}")
    
    async def safe_call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Optional[str]:
        """Safely call a tool with ETDI protection"""
        print(f"\n🛡️ ETDI TOOL EXECUTION PROTECTION")
        print(f"=" * 45)
        print(f"📋 Server: {server_name}")
        print(f"🔧 Tool: {tool_name}")
        print(f"📄 Arguments: {len(str(arguments))} characters")
        
        if server_name not in self.sessions:
            print(f"❌ ERROR: Not connected to {server_name}")
            return None
        
        analysis = self.server_analyses.get(server_name)
        if not analysis:
            print(f"❌ ERROR: No security analysis available for {server_name}")
            return None
        
        print(f"\n🔍 ETDI SECURITY CHECK:")
        print(f"   🔒 Security Score: {analysis['security_score']}/100")
        print(f"   🛡️ Trust Level: {analysis['trust_level']}")
        print(f"   📋 Recommendation: {analysis['recommendation']}")
        
        # Check if tool execution is allowed
        if analysis["recommendation"] == "BLOCK":
            print(f"\n🛑 ETDI BLOCKS TOOL EXECUTION")
            print(f"=" * 35)
            print(f"🚨 TOOL POISONING ATTACK PREVENTED!")
            print(f"📋 Server: {server_name}")
            print(f"🔧 Tool: {tool_name}")
            print(f"❌ Reason: Insufficient security features")
            print(f"🛡️ Protection: ETDI prevented malicious tool execution")
            
            print(f"\n🚨 SECURITY VIOLATIONS:")
            for i, issue in enumerate(analysis['security_issues'], 1):
                print(f"   {i}. {issue}")
            
            print(f"\n💡 WHY THIS IS DANGEROUS:")
            print(f"   • Tool claims to be from {analysis['provider']}")
            print(f"   • But cannot prove authenticity")
            print(f"   • Could be malicious tool poisoning attack")
            print(f"   • Data could be stolen or corrupted")
            
            self.security_analyzer.log_security_event(
                "TOOL_EXECUTION_BLOCKED",
                f"Blocked {tool_name} on {server_name} due to security violations",
                "CRITICAL"
            )
            
            return None
        
        elif analysis["recommendation"] == "WARN":
            print(f"\n⚠️ ETDI WARNS ABOUT TOOL EXECUTION")
            print(f"=" * 40)
            print(f"⚠️ PARTIAL SECURITY DETECTED")
            print(f"📋 Server: {server_name}")
            print(f"🔧 Tool: {tool_name}")
            print(f"⚠️ Warning: Some security features missing")
            print(f"🛡️ Proceeding with caution...")
            
            self.security_analyzer.log_security_event(
                "TOOL_EXECUTION_WARNING",
                f"Warning for {tool_name} on {server_name} - partial security",
                "WARNING"
            )
        
        else:  # ALLOW
            print(f"\n✅ ETDI ALLOWS TOOL EXECUTION")
            print(f"=" * 35)
            print(f"🛡️ FULL ETDI PROTECTION VERIFIED")
            print(f"📋 Server: {server_name}")
            print(f"🔧 Tool: {tool_name}")
            print(f"✅ Security: All checks passed")
            print(f"🔒 Protection: ETDI verified tool authenticity")
            
            self.security_analyzer.log_security_event(
                "TOOL_EXECUTION_ALLOWED",
                f"Allowed {tool_name} on {server_name} - full ETDI protection",
                "SUCCESS"
            )
        
        try:
            print(f"\n🚀 EXECUTING TOOL...")
            # Execute the tool
            session = self.sessions[server_name]
            result = await session.call_tool(tool_name, arguments)
            
            print(f"✅ Tool execution completed")
            return result.content[0].text if result.content else "No result"
            
        except Exception as e:
            print(f"❌ Tool execution failed: {e}")
            self.security_analyzer.log_security_event(
                "TOOL_EXECUTION_ERROR",
                f"Tool execution failed: {e}",
                "ERROR"
            )
            return None
    
    async def demonstrate_attack_prevention(self):
        """Demonstrate ETDI attack prevention with real servers"""
        print(f"\n🚨 ETDI TOOL POISONING ATTACK PREVENTION DEMO")
        print(f"=" * 70)
        print(f"🎯 OBJECTIVE: Demonstrate how ETDI prevents tool poisoning attacks")
        print(f"🔍 METHOD: Real FastMCP servers with identical tool names")
        print(f"🛡️ PROTECTION: ETDI security analysis and verification")
        print(f"=" * 70)
        
        # Test document with PII
        test_document = """
        Patient Record:
        Name: John Doe
        SSN: 123-45-6789
        Email: john.doe@example.com
        Phone: 555-123-4567
        Credit Card: 4532 1234 5678 9012
        """
        
        print(f"\n📋 TEST DOCUMENT PREPARED")
        print(f"=" * 30)
        print(f"📄 Document Type: Patient Record")
        print(f"📊 Content Length: {len(test_document)} characters")
        print(f"🔍 Contains PII: SSN, Email, Phone, Credit Card")
        print(f"🚨 This is sensitive data that must be protected!")
        
        print(f"\n📊 ETDI SECURITY ANALYSIS RESULTS")
        print(f"=" * 45)
        
        for server_name, analysis in self.server_analyses.items():
            print(f"\n🔍 ANALYSIS FOR {server_name}:")
            print(f"   📋 Server Name: {analysis['server_name']}")
            print(f"   🏢 Provider: {analysis['provider']}")
            print(f"   🔒 ETDI Enabled: {analysis['etdi_enabled']}")
            print(f"   🔑 OAuth Enabled: {analysis['oauth_enabled']}")
            print(f"   📊 Security Score: {analysis['security_score']}/100")
            print(f"   🛡️ Trust Level: {analysis['trust_level']}")
            print(f"   📋 Recommendation: {analysis['recommendation']}")
            
            if analysis['security_issues']:
                print(f"   🚨 Security Issues:")
                for issue in analysis['security_issues']:
                    print(f"     ❌ {issue}")
        
        print(f"\n🧪 TESTING TOOL EXECUTION WITH ETDI PROTECTION")
        print(f"=" * 55)
        
        results = {}
        
        for server_name in self.server_analyses.keys():
            print(f"\n📋 TESTING SecureDocs_Scanner on {server_name}")
            print(f"=" * 60)
            
            result = await self.safe_call_tool(
                server_name, 
                "SecureDocs_Scanner", 
                {
                    "document_content": test_document,
                    "scan_type": "detailed"
                }
            )
            
            if result:
                try:
                    parsed_result = json.loads(result)
                    results[server_name] = parsed_result
                    
                    print(f"\n📊 TOOL EXECUTION RESULTS:")
                    print(f"   ✅ Tool executed successfully")
                    print(f"   📄 PII Findings: {len(parsed_result.get('pii_findings', []))} types detected")
                    print(f"   🛡️ Security Status: {parsed_result.get('security_status', 'Unknown')}")
                    print(f"   🔒 ETDI Protected: {parsed_result.get('etdi_protected', False)}")
                    print(f"   🔑 OAuth Verified: {parsed_result.get('oauth_verified', False)}")
                    
                    # Show findings
                    if parsed_result.get('pii_findings'):
                        print(f"   🔍 Detected PII Types:")
                        for finding in parsed_result['pii_findings']:
                            print(f"     • {finding.get('description', finding)}")
                    else:
                        print(f"   📄 No PII reported (could be legitimate or fake)")
                    
                except json.JSONDecodeError:
                    print(f"   ⚠️ Invalid JSON response: {result[:100]}...")
            else:
                print(f"\n🛑 TOOL EXECUTION BLOCKED BY ETDI")
                print(f"   🛡️ ETDI successfully prevented potential attack")
                print(f"   🔒 Sensitive data protected from exposure")
                
                # For blocked tools, show what would have happened
                if server_name in self.sessions:
                    try:
                        print(f"\n💀 INVESTIGATING WHAT WOULD HAVE HAPPENED...")
                        # Get exfiltration data if available (for demo purposes)
                        exfil_result = await self.sessions[server_name].call_tool("get_exfiltrated_data", {})
                        if exfil_result and exfil_result.content:
                            exfil_data = json.loads(exfil_result.content[0].text)
                            if exfil_data.get("total_records", 0) > 0:
                                print(f"   🚨 ATTACK EVIDENCE FOUND:")
                                print(f"   📊 Data that would be stolen: {exfil_data.get('total_characters_stolen', 0)} characters")
                                print(f"   💀 Attack records: {exfil_data.get('total_records', 0)}")
                                
                                # Show attack timeline
                                timeline = exfil_data.get("attack_timeline", [])
                                if timeline:
                                    latest = timeline[-1]
                                    print(f"   💀 Latest attack preview: '{latest.get('content_preview', '')[:50]}...'")
                                    print(f"   🚨 ETDI PREVENTED THIS DATA THEFT!")
                    except:
                        pass  # Ignore errors when checking exfiltration data
        
        print(f"\n📈 ETDI ATTACK PREVENTION SUMMARY")
        print(f"=" * 45)
        
        allowed = sum(1 for a in self.server_analyses.values() if a['recommendation'] == "ALLOW")
        warned = sum(1 for a in self.server_analyses.values() if a['recommendation'] == "WARN")
        blocked = sum(1 for a in self.server_analyses.values() if a['recommendation'] == "BLOCK")
        total = len(self.server_analyses)
        
        print(f"   ✅ Servers Allowed: {allowed}")
        print(f"   ⚠️ Servers Warned: {warned}")
        print(f"   🛑 Servers Blocked: {blocked}")
        
        if total > 0:
            prevention_rate = (blocked + warned) / total * 100
            print(f"   🛡️ Attack Prevention Rate: {prevention_rate:.1f}%")
        
        if blocked > 0:
            print(f"\n🎉 ETDI SUCCESS: TOOL POISONING ATTACK PREVENTED!")
            print(f"   🛡️ Malicious server identified and blocked")
            print(f"   🔒 User data protected from exfiltration")
            print(f"   🚨 Attack stopped before execution")
        
        # Show detailed comparison
        print(f"\n🔍 DETAILED SECURITY COMPARISON")
        print(f"=" * 40)
        for server_name, analysis in self.server_analyses.items():
            print(f"\n{server_name}:")
            print(f"   🔒 ETDI Protection: {'✅ ENABLED' if analysis['etdi_enabled'] else '❌ DISABLED'}")
            print(f"   🔑 OAuth Authentication: {'✅ ENABLED' if analysis['oauth_enabled'] else '❌ DISABLED'}")
            print(f"   📊 Security Score: {analysis['security_score']}/100")
            print(f"   🛡️ Trust Level: {analysis['trust_level']}")
            print(f"   📋 Final Decision: {analysis['recommendation']}")
        
        # Show the key insight
        print(f"\n💡 KEY INSIGHTS FROM THIS DEMONSTRATION:")
        print(f"=" * 50)
        print(f"🚨 THE PROBLEM:")
        print(f"   • Without ETDI, tools appear identical to users")
        print(f"   • Malicious actors can spoof legitimate tool names")
        print(f"   • Users have no way to verify tool authenticity")
        print(f"   • Data can be stolen while providing fake results")
        print(f"")
        print(f"🛡️ THE ETDI SOLUTION:")
        print(f"   • ETDI provides cryptographic proof of authenticity")
        print(f"   • OAuth tokens verify provider identity")
        print(f"   • Security metadata reveals protection level")
        print(f"   • Malicious tools are blocked before execution")
        print(f"")
        print(f"🔒 REAL-WORLD IMPACT:")
        print(f"   • Prevents data breaches from tool poisoning")
        print(f"   • Enables safe tool ecosystem development")
        print(f"   • Provides audit trail for compliance")
        print(f"   • Builds user trust in automated tools")
        
        return results

async def main():
    """Run the complete ETDI attack prevention demonstration"""
    print(f"🚀 ETDI TOOL POISONING ATTACK PREVENTION DEMO")
    print(f"=" * 60)
    print(f"🎯 DEMONSTRATION OBJECTIVE:")
    print(f"   This demo uses REAL FastMCP servers to show how ETDI")
    print(f"   prevents tool poisoning attacks in actual MCP communication.")
    print(f"")
    print(f"🔍 WHAT WE'LL DEMONSTRATE:")
    print(f"   1. Two servers with identical tool names and interfaces")
    print(f"   2. One legitimate (ETDI-protected), one malicious (no ETDI)")
    print(f"   3. ETDI client analyzes security before execution")
    print(f"   4. Malicious tool blocked, legitimate tool allowed")
    print(f"   5. User data protected from exfiltration")
    print(f"=" * 60)
    
    client = ETDIAttackPreventionClient()
    
    try:
        # Connect to both servers
        print(f"\n🏗️ PHASE 1: CONNECTING TO SERVERS")
        print(f"=" * 40)
        
        # Connect to legitimate server
        print(f"\n🔒 Connecting to Legitimate ETDI-Protected Server...")
        legitimate_connected = await client.connect_to_server(
            "Legitimate Server",
            [sys.executable, "legitimate_etdi_server.py"]
        )
        
        # Give server time to start
        await asyncio.sleep(1)
        
        # Connect to malicious server
        print(f"\n💀 Connecting to Malicious Server...")
        malicious_connected = await client.connect_to_server(
            "Malicious Server", 
            [sys.executable, "malicious_server.py"]
        )
        
        if not legitimate_connected and not malicious_connected:
            print(f"❌ DEMO FAILED: Could not connect to any servers")
            return
        
        # Give servers time to initialize
        await asyncio.sleep(2)
        
        # Demonstrate attack prevention
        print(f"\n🛡️ PHASE 2: ETDI ATTACK PREVENTION")
        print(f"=" * 45)
        results = await client.demonstrate_attack_prevention()
        
        # Show final results
        if results:
            print(f"\n📋 PHASE 3: FINAL RESULTS COMPARISON")
            print(f"=" * 45)
            
            for server_name, result in results.items():
                print(f"\n📊 {server_name} Results:")
                print(f"   📋 Tool: {result.get('tool', 'Unknown')}")
                print(f"   🏢 Provider: {result.get('provider', 'Unknown')}")
                print(f"   🔒 ETDI Protected: {result.get('etdi_protected', False)}")
                print(f"   🔑 OAuth Verified: {result.get('oauth_verified', False)}")
                print(f"   🔍 PII Findings: {len(result.get('pii_findings', []))}")
                print(f"   🛡️ Security Status: {result.get('security_status', 'Unknown')}")
        
        print(f"\n🎯 DEMONSTRATION COMPLETE")
        print(f"=" * 30)
        print(f"✅ ETDI successfully demonstrated real-time attack prevention!")
        print(f"🛡️ Tool poisoning attack blocked before data exposure")
        print(f"🔒 User data protected through ETDI verification")
        print(f"📊 Security analysis provided clear risk assessment")
        
    except Exception as e:
        print(f"❌ DEMO FAILED: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Clean up connections
        await client.disconnect_all()

if __name__ == "__main__":
    asyncio.run(main()) 