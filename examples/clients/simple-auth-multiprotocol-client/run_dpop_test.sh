#!/usr/bin/env bash
# DPoP integration test: start simple-auth AS and simple-auth-multiprotocol RS with DPoP,
# then run automated DPoP verification tests and optional OAuth+DPoP manual test.
#
# This test is for testing DPoP + OAuth2 flow with multi-protocol support.
# Usage: in the repo root, run: ./examples/clients/simple-auth-multiprotocol-client/run_dpop_test.sh
#
# Env variables:
#   MCP_RS_PORT     - Resource Server port (default: 8002)
#   MCP_AS_PORT     - Authorization Server port (default: 9000)
#   MCP_SKIP_OAUTH  - Set to 1 to skip OAuth+DPoP manual test (default: run all)
#
# Test matrix:
#   B2: API Key authentication (DPoP should not affect)
#   A2: Bearer token without DPoP proof (should fail)
#   A1: OAuth + DPoP (requires browser authorization)
#   DPoP negative tests: wrong method, wrong URI, fake token

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SIMPLE_AUTH_SERVER="${REPO_ROOT}/examples/servers/simple-auth"
MULTIPROTOCOL_SERVER="${REPO_ROOT}/examples/servers/simple-auth-multiprotocol"
MULTIPROTOCOL_CLIENT="${REPO_ROOT}/examples/clients/simple-auth-multiprotocol-client"
RS_PORT="${MCP_RS_PORT:-8002}"
AS_PORT="${MCP_AS_PORT:-9000}"
API_KEY="dpop-test-api-key-12345"
SKIP_OAUTH="${MCP_SKIP_OAUTH:-0}"

cd "$REPO_ROOT"
echo "============================================================"
echo "Phase 4 DPoP Integration Test"
echo "============================================================"
echo "Repo root: $REPO_ROOT"
echo "AS port: $AS_PORT"
echo "RS port: $RS_PORT"
echo "API Key: $API_KEY"
echo "Skip OAuth: $SKIP_OAUTH"
echo ""

uv sync --quiet 2>/dev/null || true

wait_for_url() {
  local url="$1"
  local name="$2"
  local max=30
  local n=0
  while ! curl -sSf -o /dev/null "$url" 2>/dev/null; do
    n=$((n + 1))
    if [ "$n" -ge "$max" ]; then
      echo "Timeout waiting for $name at $url"
      return 1
    fi
    sleep 0.5
  done
  echo "$name is up at $url"
}

cleanup() {
  echo ""
  echo "Stopping servers..."
  [ -n "$AS_PID" ] && kill "$AS_PID" 2>/dev/null || true
  [ -n "$RS_PID" ] && kill "$RS_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  echo "Cleanup done."
}
trap cleanup EXIT

# Start Authorization Server
echo "Starting Authorization Server..."
cd "$SIMPLE_AUTH_SERVER"
uv run mcp-simple-auth-as --port="$AS_PORT" &
AS_PID=$!
cd "$REPO_ROOT"
wait_for_url "http://localhost:${AS_PORT}/.well-known/oauth-authorization-server" "Authorization Server"

# Start Resource Server with DPoP enabled
echo "Starting Resource Server with DPoP enabled..."
cd "$MULTIPROTOCOL_SERVER"
uv run mcp-simple-auth-multiprotocol-rs \
  --port="$RS_PORT" \
  --auth-server="http://localhost:${AS_PORT}" \
  --api-keys="$API_KEY" \
  --dpop-enabled &
RS_PID=$!
cd "$REPO_ROOT"
wait_for_url "http://localhost:${RS_PORT}/.well-known/oauth-protected-resource/mcp" "Resource Server (PRM)"

echo ""
echo "PRM (Protected Resource Metadata):"
curl -sS "http://localhost:${RS_PORT}/.well-known/oauth-protected-resource/mcp" | python3 -m json.tool 2>/dev/null | head -30 || \
  curl -sS "http://localhost:${RS_PORT}/.well-known/oauth-protected-resource/mcp" | head -c 600
echo ""

MCP_ENDPOINT="http://localhost:${RS_PORT}/mcp"
PASSED=0
FAILED=0

run_test() {
  local name="$1"
  local expected_status="$2"
  local actual_status="$3"

  if [ "$actual_status" = "$expected_status" ]; then
    echo "  PASS: $name (status=$actual_status)"
    PASSED=$((PASSED + 1))
  else
    echo "  FAIL: $name (expected=$expected_status, got=$actual_status)"
    FAILED=$((FAILED + 1))
  fi
}

echo "============================================================"
echo "Running Automated DPoP Tests"
echo "============================================================"
echo ""

# Test B2: API Key Authentication
echo "[Test B2] API Key Authentication (DPoP should not affect)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$MCP_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-API-Key: $API_KEY" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"dpop-test","version":"1.0"}}}')
run_test "API Key auth works with DPoP enabled" "200" "$STATUS"

# Test: No Authentication
echo "[Test] No Authentication (expect 401)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$MCP_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"dpop-test","version":"1.0"}}}')
run_test "No auth returns 401" "401" "$STATUS"

# Test: Check WWW-Authenticate header
echo "[Test] WWW-Authenticate header presence"
WWW_AUTH=$(curl -s -D - -o /dev/null -X POST "$MCP_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"dpop-test","version":"1.0"}}}' 2>&1 | grep -i "www-authenticate" || echo "")
if [ -n "$WWW_AUTH" ]; then
  echo "  PASS: WWW-Authenticate header present"
  PASSED=$((PASSED + 1))
else
  echo "  FAIL: WWW-Authenticate header missing"
  FAILED=$((FAILED + 1))
fi

# Test A2: Bearer token without DPoP proof (fake token)
echo "[Test A2] Bearer token without DPoP proof (fake token)"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$MCP_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer fake-bearer-token-12345" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"dpop-test","version":"1.0"}}}')
run_test "Bearer without DPoP rejected" "401" "$STATUS"

# Generate DPoP proof using Python helper (uses uv run to ensure correct venv)
generate_dpop_proof() {
  local method="$1"
  local uri="$2"
  local token="$3"
  cd "$REPO_ROOT"
  uv run python3 -c "
import hashlib
import base64
import time
import uuid
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# Generate key pair
private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
public_key = private_key.public_key()
public_numbers = public_key.public_numbers()
x_bytes = public_numbers.x.to_bytes(32, byteorder='big')
y_bytes = public_numbers.y.to_bytes(32, byteorder='big')

jwk = {
    'kty': 'EC',
    'crv': 'P-256',
    'x': base64.urlsafe_b64encode(x_bytes).rstrip(b'=').decode('ascii'),
    'y': base64.urlsafe_b64encode(y_bytes).rstrip(b'=').decode('ascii'),
}

claims = {
    'jti': str(uuid.uuid4()),
    'htm': '$method',
    'htu': '$uri',
    'iat': int(time.time()),
}

token = '$token'
if token:
    token_hash = hashlib.sha256(token.encode('ascii')).digest()
    claims['ath'] = base64.urlsafe_b64encode(token_hash).rstrip(b'=').decode('ascii')

header = {'typ': 'dpop+jwt', 'alg': 'ES256', 'jwk': jwk}
private_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
proof = jwt.encode(claims, private_pem, algorithm='ES256', headers=header)
print(proof)
"
}

# Test: DPoP proof with fake token
echo "[Test] DPoP proof with fake token (expect 401)"
FAKE_TOKEN="fake-access-token-12345"
DPOP_PROOF=$(generate_dpop_proof "POST" "$MCP_ENDPOINT" "$FAKE_TOKEN")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$MCP_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: DPoP $FAKE_TOKEN" \
  -H "DPoP: $DPOP_PROOF" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"dpop-test","version":"1.0"}}}')
run_test "DPoP with fake token rejected" "401" "$STATUS"

# Test: DPoP proof with wrong HTTP method (htm mismatch)
echo "[Test] DPoP proof wrong method (htm=GET for POST request)"
DPOP_PROOF_WRONG_METHOD=$(generate_dpop_proof "GET" "$MCP_ENDPOINT" "$FAKE_TOKEN")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$MCP_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: DPoP $FAKE_TOKEN" \
  -H "DPoP: $DPOP_PROOF_WRONG_METHOD" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"dpop-test","version":"1.0"}}}')
run_test "DPoP htm mismatch rejected" "401" "$STATUS"

# Test: DPoP proof with wrong URI (htu mismatch)
echo "[Test] DPoP proof wrong URI (htu mismatch)"
DPOP_PROOF_WRONG_URI=$(generate_dpop_proof "POST" "http://localhost:9999/wrong" "$FAKE_TOKEN")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$MCP_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: DPoP $FAKE_TOKEN" \
  -H "DPoP: $DPOP_PROOF_WRONG_URI" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"dpop-test","version":"1.0"}}}')
run_test "DPoP htu mismatch rejected" "401" "$STATUS"

# Test: DPoP proof without Authorization header
echo "[Test] DPoP proof without Authorization header (expect 401)"
DPOP_PROOF_NO_TOKEN=$(generate_dpop_proof "POST" "$MCP_ENDPOINT" "")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$MCP_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "DPoP: $DPOP_PROOF_NO_TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"dpop-test","version":"1.0"}}}')
run_test "DPoP proof without token rejected" "401" "$STATUS"

echo ""
echo "============================================================"
echo "Automated Test Summary"
echo "============================================================"
echo "  Passed: $PASSED"
echo "  Failed: $FAILED"
echo ""

if [ "$FAILED" -gt 0 ]; then
  echo "WARNING: Some automated tests failed!"
fi

# A1: OAuth + DPoP manual test
if [ "$SKIP_OAUTH" = "1" ]; then
  echo "Skipping OAuth+DPoP manual test (MCP_SKIP_OAUTH=1)"
  echo ""
  echo "============================================================"
  echo "Final Result: $PASSED passed, $FAILED failed (automated only)"
  echo "============================================================"
else
  echo ""
  echo "============================================================"
  echo "[Test A1] OAuth + DPoP Manual Test"
  echo "============================================================"
  echo ""
  echo "This test requires browser authorization."
  echo "The client will:"
  echo "  1. Open your browser for OAuth authorization"
  echo "  2. After authorization, connect with DPoP-bound access token"
  echo "  3. You should see 'DPoP proof present, verification enabled' in server logs"
  echo ""
  echo "At the mcp> prompt, run:"
  echo "  list              - List available tools"
  echo "  call get_time {}  - Call the get_time tool"
  echo "  quit              - Exit the client"
  echo ""
  echo "Expected: All commands should succeed with DPoP authentication."
  echo ""
  read -p "Press Enter to start OAuth+DPoP test (or Ctrl+C to skip)..."
  echo ""

  cd "$MULTIPROTOCOL_CLIENT"
  MCP_SERVER_URL="$MCP_ENDPOINT" \
  MCP_USE_OAUTH=1 \
  MCP_DPOP_ENABLED=1 \
  uv run mcp-simple-auth-multiprotocol-client

  echo ""
  echo "============================================================"
  echo "Manual Test Complete"
  echo "============================================================"
  echo "Did the OAuth+DPoP test succeed? (list/call commands worked?)"
  echo "Check server logs for: 'Authentication successful with DPoP'"
  echo ""
  echo "Final Result: $PASSED passed, $FAILED failed (automated)"
  echo "              + A1 OAuth+DPoP (manual verification required)"
  echo "============================================================"
fi
