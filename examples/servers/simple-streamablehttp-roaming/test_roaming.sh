#!/bin/bash

# Test script demonstrating session roaming across MCP server instances
#
# This script:
# 1. Creates a session on Instance 1 (port 3001)
# 2. Calls a tool on Instance 1
# 3. Uses the same session on Instance 2 (port 3002)
# 4. Calls a tool on Instance 2
# 5. Verifies the session roamed successfully

set -e  # Exit on error

INSTANCE_1_PORT=3001
INSTANCE_2_PORT=3002

echo "🧪 Testing Session Roaming Across MCP Instances"
echo "================================================"
echo ""

# Check if instances are running
echo "📡 Checking if server instances are running..."
if ! curl -s -o /dev/null -w "%{http_code}" http://localhost:$INSTANCE_1_PORT/mcp >/dev/null 2>&1; then
    echo "❌ Instance 1 (port $INSTANCE_1_PORT) is not running"
    echo "   Start it with: uv run mcp-streamablehttp-roaming --port $INSTANCE_1_PORT --instance-id instance-1"
    exit 1
fi

if ! curl -s -o /dev/null -w "%{http_code}" http://localhost:$INSTANCE_2_PORT/mcp >/dev/null 2>&1; then
    echo "❌ Instance 2 (port $INSTANCE_2_PORT) is not running"
    echo "   Start it with: uv run mcp-streamablehttp-roaming --port $INSTANCE_2_PORT --instance-id instance-2"
    exit 1
fi

echo "✅ Both instances are running"
echo ""

# Step 1: Create session on Instance 1
echo "📍 Step 1: Creating session on Instance 1 (port $INSTANCE_1_PORT)..."
RESPONSE=$(curl -s -i -X POST http://localhost:$INSTANCE_1_PORT/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "1.0.0",
      "capabilities": {},
      "clientInfo": {"name": "test-client", "version": "1.0.0"}
    }
  }')

# Extract session ID from response headers
SESSION_ID=$(echo "$RESPONSE" | grep -i "mcp-session-id:" | cut -d' ' -f2 | tr -d '\r\n')

if [ -z "$SESSION_ID" ]; then
    echo "❌ Failed to create session on Instance 1"
    echo "Response:"
    echo "$RESPONSE"
    exit 1
fi

echo "✅ Session created: $SESSION_ID"
echo ""

# Step 2: Call tool on Instance 1
echo "📍 Step 2: Calling tool on Instance 1..."
RESPONSE_1=$(curl -s -X POST http://localhost:$INSTANCE_1_PORT/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Session-ID: $SESSION_ID" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "get-instance-info",
      "arguments": {
        "message": "Request from Instance 1"
      }
    }
  }')

# Check if Instance 1 handled it
if echo "$RESPONSE_1" | grep -q "instance-1"; then
    echo "✅ Tool executed successfully on Instance 1"
else
    echo "⚠️  Unexpected response from Instance 1:"
    echo "$RESPONSE_1"
fi
echo ""

# Step 3: Use same session on Instance 2 (session roaming!)
echo "📍 Step 3: Using same session on Instance 2 (port $INSTANCE_2_PORT)..."
RESPONSE_2=$(curl -s -X POST http://localhost:$INSTANCE_2_PORT/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Session-ID: $SESSION_ID" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "get-instance-info",
      "arguments": {
        "message": "Request from Instance 2 - session roamed!"
      }
    }
  }')

# Check if Instance 2 handled it
if echo "$RESPONSE_2" | grep -q "instance-2"; then
    echo "✅ Session roamed to Instance 2!"
    echo ""
    echo "🎉 SUCCESS! Session roaming works!"
    echo ""
    echo "Details:"
    echo "--------"
    echo "• Session ID: $SESSION_ID"
    echo "• Instance 1 handled initial request (port $INSTANCE_1_PORT)"
    echo "• Instance 2 handled subsequent request (port $INSTANCE_2_PORT)"
    echo "• Same session used across both instances ✅"
    echo ""
    echo "This demonstrates that:"
    echo "✓ Sessions are not tied to specific instances"
    echo "✓ Redis EventStore enables session roaming"
    echo "✓ No sticky sessions required"
    echo "✓ Load balancers can route freely"
    echo ""
elif echo "$RESPONSE_2" | grep -q "Bad Request"; then
    echo "❌ Instance 2 rejected the session (session roaming not working)"
    echo "Response:"
    echo "$RESPONSE_2"
    echo ""
    echo "Possible issues:"
    echo "- Redis not running (start with: docker run -p 6379:6379 redis:latest)"
    echo "- Instances not using same Redis URL"
    echo "- EventStore not configured properly"
    exit 1
else
    echo "⚠️  Unexpected response from Instance 2:"
    echo "$RESPONSE_2"
    exit 1
fi
