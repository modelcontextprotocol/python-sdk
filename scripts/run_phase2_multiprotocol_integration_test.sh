#!/usr/bin/env bash
# Phase 2 multi-protocol integration test: start simple-auth-multiprotocol RS (and optionally AS for OAuth),
# then run client with API Key, OAuth, or Mutual TLS (placeholder).
# Usage: from repo root, run: ./scripts/run_phase2_multiprotocol_integration_test.sh
# Env: MCP_PHASE2_PROTOCOL=api_key (default) | oauth | mutual_tls (client will show "not implemented" for mTLS).
# For api_key/mutual_tls: simple-auth-multiprotocol-client; for oauth: simple-auth-client (complete OAuth in browser).
# You must run at mcp> prompt: list, call get_time {}, quit.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIMPLE_AUTH_SERVER="${REPO_ROOT}/examples/servers/simple-auth"
MULTIPROTOCOL_SERVER="${REPO_ROOT}/examples/servers/simple-auth-multiprotocol"
MULTIPROTOCOL_CLIENT="${REPO_ROOT}/examples/clients/simple-auth-multiprotocol-client"
SIMPLE_AUTH_CLIENT="${REPO_ROOT}/examples/clients/simple-auth-client"
RS_PORT="${MCP_RS_PORT:-8002}"
AS_PORT="${MCP_AS_PORT:-9000}"
PROTOCOL="${MCP_PHASE2_PROTOCOL:-api_key}"

cd "$REPO_ROOT"
echo "Repo root: $REPO_ROOT"
echo "Protocol: $PROTOCOL"

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
if [ "$PROTOCOL" = "oauth" ]; then
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
if [ "$PROTOCOL" = "oauth" ]; then
  echo "Starting simple-auth-client (OAuth). Complete OAuth in the browser, then run: list, call get_time {}, quit"
  echo ""
  cd "$SIMPLE_AUTH_CLIENT"
  MCP_SERVER_PORT="$RS_PORT" MCP_TRANSPORT_TYPE=streamable-http uv run mcp-simple-auth-client
elif [ "$PROTOCOL" = "mutual_tls" ]; then
  echo "Starting simple-auth-multiprotocol-client (mTLS placeholder). At mcp> run: list, call get_time {}, quit"
  echo ""
  cd "$MULTIPROTOCOL_CLIENT"
  unset MCP_API_KEY
  MCP_SERVER_URL="http://localhost:${RS_PORT}/mcp" uv run mcp-simple-auth-multiprotocol-client
else
  echo "Starting simple-auth-multiprotocol-client (API Key). At mcp> run: list, call get_time {}, quit"
  echo ""
  cd "$MULTIPROTOCOL_CLIENT"
  MCP_SERVER_URL="http://localhost:${RS_PORT}/mcp" MCP_API_KEY="demo-api-key-12345" uv run mcp-simple-auth-multiprotocol-client
fi
