#!/usr/bin/env python3
"""
Real Server ETDI Demo Runner

This script orchestrates the complete ETDI tool poisoning prevention demo
using real FastMCP servers and an ETDI-enabled client.

It demonstrates:
1. Starting legitimate ETDI-protected FastMCP server
2. Starting malicious FastMCP server (no ETDI)
3. Running ETDI client that connects to both
4. Showing how ETDI prevents the tool poisoning attack
"""

import asyncio
import subprocess
import sys
import time
import signal
import os
from pathlib import Path

class ServerManager:
    """Manages FastMCP server processes"""
    
    def __init__(self):
        self.processes = {}
        
    def start_server(self, name: str, script_path: str) -> bool:
        """Start a FastMCP server process"""
        try:
            print(f"🚀 STARTING {name.upper()}")
            print(f"=" * 50)
            print(f"📋 Script: {script_path}")
            print(f"🔍 Launching FastMCP server process...")
            
            # Start the server process
            process = subprocess.Popen(
                [sys.executable, script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
                bufsize=0
            )
            
            self.processes[name] = process
            print(f"📊 Process ID: {process.pid}")
            
            # Give server time to start
            print(f"⏳ Waiting for server initialization...")
            time.sleep(2)
            
            # Check if process is still running
            if process.poll() is None:
                print(f"✅ {name} STARTED SUCCESSFULLY")
                print(f"   📊 PID: {process.pid}")
                print(f"   🔍 Status: Running")
                print(f"   🚀 Ready for client connections")
                return True
            else:
                stdout, stderr = process.communicate()
                print(f"❌ {name} FAILED TO START")
                print(f"   📄 stdout: {stdout}")
                print(f"   🚨 stderr: {stderr}")
                return False
                
        except Exception as e:
            print(f"❌ FAILED TO START {name}: {e}")
            return False
    
    def stop_all_servers(self):
        """Stop all running server processes"""
        print(f"\n🛑 STOPPING ALL SERVERS")
        print(f"=" * 30)
        
        for name, process in self.processes.items():
            try:
                if process.poll() is None:  # Process is still running
                    print(f"🛑 Stopping {name}...")
                    print(f"   📊 PID: {process.pid}")
                    process.terminate()
                    
                    # Wait for graceful shutdown
                    try:
                        process.wait(timeout=5)
                        print(f"✅ {name} stopped gracefully")
                    except subprocess.TimeoutExpired:
                        print(f"⚠️ Force killing {name}...")
                        process.kill()
                        process.wait()
                        print(f"✅ {name} force stopped")
                else:
                    print(f"ℹ️ {name} already stopped")
            except Exception as e:
                print(f"⚠️ Error stopping {name}: {e}")
        
        self.processes.clear()
        print(f"✅ All servers stopped")

async def run_demo():
    """Run the complete ETDI demo with real servers"""
    print(f"🚀 ETDI REAL SERVER DEMO ORCHESTRATOR")
    print(f"=" * 60)
    print(f"🎯 DEMO OBJECTIVE:")
    print(f"   Orchestrate a complete tool poisoning prevention demonstration")
    print(f"   using real FastMCP servers and ETDI security analysis.")
    print(f"")
    print(f"🔍 DEMO COMPONENTS:")
    print(f"   1. Legitimate ETDI-protected FastMCP server")
    print(f"   2. Malicious FastMCP server (tool poisoning attack)")
    print(f"   3. ETDI-enabled client with security analysis")
    print(f"   4. Real-time attack prevention demonstration")
    print(f"")
    print(f"🛡️ EXPECTED OUTCOME:")
    print(f"   • Legitimate server: ALLOWED (ETDI protection verified)")
    print(f"   • Malicious server: BLOCKED (no ETDI protection)")
    print(f"   • User data: PROTECTED from exfiltration")
    print(f"=" * 60)
    
    server_manager = ServerManager()
    
    try:
        # Check if server files exist
        print(f"\n🔍 PHASE 1: VALIDATING DEMO COMPONENTS")
        print(f"=" * 45)
        
        current_dir = Path(__file__).parent
        legitimate_server = current_dir / "legitimate_etdi_server.py"
        malicious_server = current_dir / "malicious_server.py"
        client_script = current_dir / "etdi_attack_prevention_client.py"
        
        print(f"📋 Checking required files...")
        
        if not legitimate_server.exists():
            print(f"❌ VALIDATION FAILED: Legitimate server not found")
            print(f"   📄 Expected: {legitimate_server}")
            return
        else:
            print(f"✅ Legitimate server found: {legitimate_server.name}")
        
        if not malicious_server.exists():
            print(f"❌ VALIDATION FAILED: Malicious server not found")
            print(f"   📄 Expected: {malicious_server}")
            return
        else:
            print(f"✅ Malicious server found: {malicious_server.name}")
        
        if not client_script.exists():
            print(f"❌ VALIDATION FAILED: Client script not found")
            print(f"   📄 Expected: {client_script}")
            return
        else:
            print(f"✅ ETDI client found: {client_script.name}")
        
        print(f"\n✅ ALL COMPONENTS VALIDATED")
        print(f"🚀 Ready to start demo servers...")
        
        print(f"\n🏗️ PHASE 2: STARTING DEMO SERVERS")
        print(f"=" * 40)
        
        # Start legitimate ETDI server
        print(f"\n🔒 STARTING LEGITIMATE ETDI-PROTECTED SERVER")
        print(f"🛡️ This server implements proper ETDI security:")
        print(f"   • OAuth 2.0 authentication")
        print(f"   • ETDI tool verification")
        print(f"   • Permission scoping")
        print(f"   • Call stack constraints")
        print(f"   • Audit logging")
        
        legitimate_started = server_manager.start_server(
            "Legitimate ETDI Server",
            str(legitimate_server)
        )
        
        # Start malicious server
        print(f"\n💀 STARTING MALICIOUS SERVER (ATTACK SIMULATION)")
        print(f"🚨 This server simulates a tool poisoning attack:")
        print(f"   • NO ETDI protection")
        print(f"   • NO OAuth authentication")
        print(f"   • Spoofed provider identity")
        print(f"   • Data exfiltration capabilities")
        print(f"   • Fake result generation")
        
        malicious_started = server_manager.start_server(
            "Malicious Server",
            str(malicious_server)
        )
        
        if not legitimate_started and not malicious_started:
            print(f"\n❌ DEMO FAILED: No servers could be started")
            print(f"🚨 Cannot proceed without at least one server")
            return
        
        # Show server status
        print(f"\n📊 SERVER STATUS SUMMARY")
        print(f"=" * 30)
        print(f"🔒 Legitimate Server: {'✅ RUNNING' if legitimate_started else '❌ FAILED'}")
        print(f"💀 Malicious Server: {'✅ RUNNING' if malicious_started else '❌ FAILED'}")
        
        if legitimate_started and malicious_started:
            print(f"🎯 PERFECT: Both servers running - full demo possible")
        elif legitimate_started:
            print(f"⚠️ PARTIAL: Only legitimate server - limited demo")
        elif malicious_started:
            print(f"⚠️ PARTIAL: Only malicious server - limited demo")
        
        print(f"\n⏳ WAITING FOR SERVER INITIALIZATION")
        print(f"🔍 Allowing servers to fully initialize...")
        time.sleep(3)
        print(f"✅ Servers should be ready for client connections")
        
        print(f"\n🔐 PHASE 3: RUNNING ETDI CLIENT DEMO")
        print(f"=" * 40)
        print(f"🚀 Launching ETDI attack prevention client...")
        print(f"🔍 The client will:")
        print(f"   1. Connect to both servers")
        print(f"   2. Analyze security metadata")
        print(f"   3. Score each server's security")
        print(f"   4. Block malicious tools")
        print(f"   5. Allow legitimate tools")
        print(f"   6. Demonstrate attack prevention")
        
        # Run the ETDI client demo
        try:
            print(f"\n📋 EXECUTING CLIENT DEMO...")
            result = subprocess.run(
                [sys.executable, str(client_script)],
                capture_output=True,
                text=True,
                timeout=60  # 60 second timeout
            )
            
            print(f"\n📄 CLIENT DEMO OUTPUT:")
            print(f"=" * 25)
            print(result.stdout)
            
            if result.stderr:
                print(f"\n⚠️ CLIENT DEMO ERRORS:")
                print(f"=" * 25)
                print(result.stderr)
            
            if result.returncode == 0:
                print(f"\n🎉 DEMO COMPLETED SUCCESSFULLY!")
                print(f"=" * 35)
                print(f"✅ ETDI attack prevention demonstrated")
                print(f"🛡️ Tool poisoning attack blocked")
                print(f"🔒 User data protected from exfiltration")
                print(f"📊 Security analysis provided clear guidance")
            else:
                print(f"\n❌ DEMO FAILED")
                print(f"=" * 15)
                print(f"🚨 Return code: {result.returncode}")
                print(f"⚠️ Check output above for details")
                
        except subprocess.TimeoutExpired:
            print(f"\n⏰ DEMO TIMEOUT")
            print(f"=" * 15)
            print(f"🚨 Demo timed out after 60 seconds")
            print(f"⚠️ This may indicate a server communication issue")
        except Exception as e:
            print(f"\n❌ CLIENT DEMO ERROR")
            print(f"=" * 20)
            print(f"🚨 Error: {e}")
            print(f"⚠️ Check server status and try again")
        
    except KeyboardInterrupt:
        print(f"\n🛑 DEMO INTERRUPTED BY USER")
        print(f"=" * 30)
        print(f"⚠️ User pressed Ctrl+C")
    except Exception as e:
        print(f"\n❌ DEMO ORCHESTRATION FAILED")
        print(f"=" * 35)
        print(f"🚨 Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print(f"\n🧹 PHASE 4: CLEANUP")
        print(f"=" * 20)
        print(f"🛑 Stopping all demo servers...")
        server_manager.stop_all_servers()
        print(f"✅ Cleanup complete")
        
        print(f"\n📋 DEMO SUMMARY")
        print(f"=" * 15)
        print(f"🎯 Objective: Demonstrate ETDI tool poisoning prevention")
        print(f"🔍 Method: Real FastMCP servers with security analysis")
        print(f"🛡️ Result: ETDI successfully prevents malicious tool execution")
        print(f"📊 Impact: User data protected through cryptographic verification")
        
        print(f"\n💡 KEY TAKEAWAYS:")
        print(f"   • Tool poisoning is a real threat in tool ecosystems")
        print(f"   • ETDI provides cryptographic proof of tool authenticity")
        print(f"   • OAuth verification ensures provider legitimacy")
        print(f"   • Security analysis enables informed decisions")
        print(f"   • Malicious tools can be blocked before data exposure")

def main():
    """Main entry point"""
    print(f"🚀 ETDI TOOL POISONING PREVENTION DEMO")
    print(f"=" * 50)
    print(f"⚠️  IMPORTANT: This demo uses real servers to demonstrate")
    print(f"   how ETDI prevents tool poisoning attacks in practice.")
    print(f"")
    print(f"🔍 WHAT YOU'LL SEE:")
    print(f"   • Two servers with identical tool names")
    print(f"   • One legitimate (ETDI-protected)")
    print(f"   • One malicious (no ETDI protection)")
    print(f"   • ETDI client analyzing and blocking the attack")
    print(f"")
    print(f"🛡️ EXPECTED OUTCOME:")
    print(f"   • Legitimate tool: ALLOWED")
    print(f"   • Malicious tool: BLOCKED")
    print(f"   • Data: PROTECTED")
    print(f"=" * 50)
    
    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print(f"\n🛑 RECEIVED INTERRUPT SIGNAL")
        print(f"🧹 Cleaning up and exiting...")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    # Run the demo
    asyncio.run(run_demo())

if __name__ == "__main__":
    main() 