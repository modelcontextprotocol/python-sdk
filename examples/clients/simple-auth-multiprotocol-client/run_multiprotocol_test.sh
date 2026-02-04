#!/usr/bin/env bash
# Multi-protocol integration test (MultiProtocolAuthProvider):
# start simple-auth-multiprotocol RS (and optionally AS for OAuth),
# then run simple-auth-multiprotocol-client with API Key, OAuth, OAuth+DPoP, or Mutual TLS (placeholder).
# Usage: in the repo root, run: ./examples/clients/simple-auth-multiprotocol-client/run_multiprotocol_test.sh
# Env: MCP_AUTH_PROTOCOL=api_key (default) | oauth | oauth_dpop | mutual_tls
# For api_key/mutual_tls: script runs non-interactive commands (list/call/quit) and asserts PASS/FAIL.
# For oauth/oauth_dpop: complete OAuth in browser, then run: list, call get_time {}, quit.
# Optional: MCP_SKIP_OAUTH=1 to skip oauth/oauth_dpop manual cases.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SIMPLE_AUTH_SERVER="${REPO_ROOT}/examples/servers/simple-auth"
MULTIPROTOCOL_SERVER="${REPO_ROOT}/examples/servers/simple-auth-multiprotocol"
MULTIPROTOCOL_CLIENT="${REPO_ROOT}/examples/clients/simple-auth-multiprotocol-client"
RS_PORT="${MCP_RS_PORT:-8002}"
AS_PORT="${MCP_AS_PORT:-9000}"
PROTOCOL="${MCP_AUTH_PROTOCOL:-api_key}"
SKIP_OAUTH="${MCP_SKIP_OAUTH:-0}"

cd "$REPO_ROOT"
echo "Repo root: $REPO_ROOT"
echo "Protocol: $PROTOCOL"
echo "Skip OAuth: $SKIP_OAUTH"

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
  echo "Stopping servers..."
  [ -n "$AS_PID" ] && kill "$AS_PID" 2>/dev/null || true
  [ -n "$RS_PID" ] && kill "$RS_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT

# Start Authorization Server only for OAuth
if [ "$PROTOCOL" = "oauth" ] || [ "$PROTOCOL" = "oauth_dpop" ]; then
  cd "$SIMPLE_AUTH_SERVER"
  uv run mcp-simple-auth-as --port="$AS_PORT" &
  AS_PID=$!
  cd "$REPO_ROOT"
  wait_for_url "http://localhost:${AS_PORT}/.well-known/oauth-authorization-server" "Authorization Server"
fi

# Start multi-protocol Resource Server
cd "$MULTIPROTOCOL_SERVER"
if [ "$PROTOCOL" = "oauth" ]; then
  uv run mcp-simple-auth-multiprotocol-rs --port="$RS_PORT" --auth-server="http://localhost:${AS_PORT}" --api-keys="demo-api-key-12345" &
elif [ "$PROTOCOL" = "oauth_dpop" ]; then
  uv run mcp-simple-auth-multiprotocol-rs --port="$RS_PORT" --auth-server="http://localhost:${AS_PORT}" --api-keys="demo-api-key-12345" --dpop-enabled &
else
  uv run mcp-simple-auth-multiprotocol-rs --port="$RS_PORT" --api-keys="demo-api-key-12345" &
fi
RS_PID=$!
cd "$REPO_ROOT"

wait_for_url "http://localhost:${RS_PORT}/.well-known/oauth-protected-resource/mcp" "Multi-protocol RS (PRM)"

echo ""
echo "PRM (auth_protocols etc.):"
curl -sS "http://localhost:${RS_PORT}/.well-known/oauth-protected-resource/mcp" | head -c 600
echo ""
echo ""

# Run client by protocol
if [ "$PROTOCOL" = "oauth" ] || [ "$PROTOCOL" = "oauth_dpop" ]; then
  if [ "$SKIP_OAUTH" = "1" ]; then
    echo "Skipping OAuth manual test (MCP_SKIP_OAUTH=1)"
    exit 0
  fi
  echo "Starting simple-auth-multiprotocol-client (OAuth). Complete OAuth in the browser, then run: list, call get_time {}, quit"
  echo ""
  cd "$MULTIPROTOCOL_CLIENT"
  MCP_SERVER_URL="http://localhost:${RS_PORT}/mcp" \
  MCP_USE_OAUTH=1 \
  MCP_DPOP_ENABLED=$([ "$PROTOCOL" = "oauth_dpop" ] && echo 1 || echo 0) \
  MCP_AUTH_PROTOCOL="$PROTOCOL" \
  uv run mcp-simple-auth-multiprotocol-client
elif [ "$PROTOCOL" = "mutual_tls" ]; then
  echo "Running mTLS placeholder selection (expect not implemented)"
  echo ""
  cd "$MULTIPROTOCOL_CLIENT"
  set +e
  OUT=$(MCP_SERVER_URL="http://localhost:${RS_PORT}/mcp" MCP_AUTH_PROTOCOL="mutual_tls" uv run mcp-simple-auth-multiprotocol-client 2>&1)
  CODE=$?
  set -e
  echo "$OUT" | head -60
  if echo "$OUT" | grep -q "Mutual TLS not implemented"; then
    echo "PASS: mutual_tls placeholder reported not implemented"
    exit 0
  fi
  echo "FAIL: mutual_tls placeholder did not report expected error (exit=$CODE)"
  exit 1
else
  echo "Running API Key flow (non-interactive): list, call get_time {}, quit"
  echo ""
  cd "$MULTIPROTOCOL_CLIENT"
  set +e
  OUT=$(printf "list\ncall get_time {}\nquit\n" | MCP_SERVER_URL="http://localhost:${RS_PORT}/mcp" MCP_API_KEY="demo-api-key-12345" MCP_AUTH_PROTOCOL="api_key" uv run mcp-simple-auth-multiprotocol-client 2>&1)
  CODE=$?
  set -e
  echo "$OUT" | head -80
  if [ "$CODE" -eq 0 ] && echo "$OUT" | grep -q "Session initialized" && ! echo "$OUT" | grep -q "Session terminated"; then
    echo "PASS: api_key flow succeeded"
    exit 0
  fi
  echo "FAIL: api_key flow failed (exit=$CODE)"
  exit 1
fi
