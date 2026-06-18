#!/bin/bash
set -e

PORT="${PORT:-3001}"
SERVER_URL="http://localhost:${PORT}/mcp"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../../.."

# Refuse to start if something is already listening on the port. The readiness
# check below cannot tell our server apart from a stale one, so a leftover
# listener would mean silently running conformance against old code.
if (: > "/dev/tcp/localhost/${PORT}") 2>/dev/null; then
    echo "Error: port ${PORT} is already in use." >&2
    echo "Stop the stale process first (lsof -ti:${PORT} -sTCP:LISTEN | xargs kill) or set PORT to a free port." >&2
    exit 1
fi

echo "Starting mcp-everything-server on port ${PORT}..."
uv run --frozen mcp-everything-server --port "$PORT" &
SERVER_PID=$!

cleanup() {
    echo "Stopping server (PID: ${SERVER_PID})..."
    kill $SERVER_PID 2>/dev/null || true
    wait $SERVER_PID 2>/dev/null || true
}
trap cleanup EXIT

# Wait for server to be ready. --max-time keeps a hung listener from wedging
# the loop, and a dead server process fails fast instead of retrying.
echo "Waiting for server to be ready..."
MAX_RETRIES=30
RETRY_COUNT=0
while ! curl -s --max-time 2 "$SERVER_URL" > /dev/null 2>&1; do
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        echo "Server process exited unexpectedly" >&2
        exit 1
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "Server failed to start after ${MAX_RETRIES} retries" >&2
        exit 1
    fi
    sleep 0.5
done

echo "Server ready at $SERVER_URL"

npx --yes @modelcontextprotocol/conformance@"${CONFORMANCE_VERSION:?set CONFORMANCE_VERSION (pinned in .github/workflows/conformance.yml)}" \
    server --url "$SERVER_URL" "$@"
