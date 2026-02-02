#!/usr/bin/env bash
# OAuth2 integration test: start simple-auth (AS + RS) and run simple-auth-client.
# This test is for testing Oauth2 flow with multi-protocol support.
# Usage: in the repo root, run: ./examples/clients/simple-auth-multiprotocol-client/run_oauth2_test.sh
# You must complete OAuth in the browser and run list / call get_time / quit at the mcp> prompt.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SIMPLE_AUTH_SERVER="${REPO_ROOT}/examples/servers/simple-auth"
SIMPLE_AUTH_CLIENT="${REPO_ROOT}/examples/clients/simple-auth-client"
AS_PORT=9000
RS_PORT=8001

cd "$REPO_ROOT"
echo "Repo root: $REPO_ROOT"

# Ensure deps (simple-auth and simple-auth-client are workspace examples)
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

# Start Authorization Server
cd "$SIMPLE_AUTH_SERVER"
uv run mcp-simple-auth-as --port="$AS_PORT" &
AS_PID=$!
cd "$REPO_ROOT"

# Start Resource Server
cd "$SIMPLE_AUTH_SERVER"
uv run mcp-simple-auth-rs --port="$RS_PORT" --auth-server="http://localhost:$AS_PORT" --transport=streamable-http &
RS_PID=$!
cd "$REPO_ROOT"

# Wait for AS and RS (PRM path includes /mcp when server_url is http://localhost:8001/mcp)
wait_for_url "http://localhost:$AS_PORT/.well-known/oauth-authorization-server" "Authorization Server"
wait_for_url "http://localhost:$RS_PORT/.well-known/oauth-protected-resource/mcp" "Resource Server (PRM)"

# Optional: print PRM (Phase 1 backward compat: resource + authorization_servers; mcp_* may appear)
echo ""
echo "PRM (RFC 9728 + optional Phase 1 fields):"
curl -sS "http://localhost:$RS_PORT/.well-known/oauth-protected-resource/mcp" | head -c 500
echo ""
echo ""

# Run client (foreground); user completes OAuth in browser and runs list / call get_time / quit
echo "Starting simple-auth-client. Complete OAuth in the browser, then run: list, call get_time {}, quit"
echo ""
cd "$SIMPLE_AUTH_CLIENT"
MCP_SERVER_PORT="$RS_PORT" MCP_TRANSPORT_TYPE=streamable-http uv run mcp-simple-auth-client
