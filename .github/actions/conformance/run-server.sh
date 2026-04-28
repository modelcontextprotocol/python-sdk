#!/bin/bash
set -e

PORT="${PORT:-3001}"
SERVER_URL="http://localhost:${PORT}/mcp"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../../.."

# Start everything-server
uv run --frozen mcp-everything-server --port "$PORT" &
SERVER_PID=$!
trap "kill $SERVER_PID 2>/dev/null || true; wait $SERVER_PID 2>/dev/null || true" EXIT

# Wait for server to be ready
MAX_RETRIES=30
RETRY_COUNT=0
while ! curl -s "$SERVER_URL" > /dev/null 2>&1; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "Server failed to start after ${MAX_RETRIES} retries" >&2
        exit 1
    fi
    sleep 0.5
done

echo "Server ready at $SERVER_URL"

# Run conformance tests
npx @modelcontextprotocol/conformance@0.1.10 server --url "$SERVER_URL" "$@"
