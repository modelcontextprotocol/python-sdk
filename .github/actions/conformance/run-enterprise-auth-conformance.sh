#!/bin/bash
set -e

# Enterprise Auth Conformance Test Runner
# Runs conformance tests for SEP-990 enterprise managed authorization
#
# This script uses the @modelcontextprotocol/conformance package v0.1.14+
# which includes enterprise auth scenarios from PR #110

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../../.."

echo "==================================================================="
echo "  Enterprise Auth Conformance Tests (SEP-990)"
echo "==================================================================="
echo ""
echo "Package: @modelcontextprotocol/conformance@0.1.14"
echo "Scenario: auth/cross-app-access-complete-flow"
echo "PR: https://github.com/modelcontextprotocol/conformance/pull/110"
echo "Release: https://github.com/modelcontextprotocol/conformance/releases/tag/v0.1.14"
echo ""

# Load nvm if available
export NVM_DIR="$HOME/.nvm"
if [ -s "$NVM_DIR/nvm.sh" ]; then
    \. "$NVM_DIR/nvm.sh"

    # Try to use Node 22 if available, otherwise any version >= 18
    if nvm ls 22 &> /dev/null; then
        echo "Switching to Node.js 22..."
        nvm use 22
    elif nvm ls 20 &> /dev/null; then
        echo "Switching to Node.js 20..."
        nvm use 20
    elif nvm ls 18 &> /dev/null; then
        echo "Switching to Node.js 18..."
        nvm use 18
    fi
fi

# Check Node version after attempting to switch
NODE_VERSION=$(node --version | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "⚠️  Error: Node.js version $NODE_VERSION detected"
    echo "   Conformance package requires Node.js >= 18"
    echo "   Current version: $(node --version)"
    echo ""
    echo "   To run locally, install Node 18+ via nvm:"
    echo "   nvm install 22"
    echo "   nvm use 22"
    echo ""
    echo "   Then run this script again."
    echo ""
    exit 1
fi

echo "Using Node.js $(node --version)"
echo ""

# Ensure dependencies are synced
echo "Syncing dependencies..."
uv sync --frozen --all-extras --package mcp

echo ""
echo "Running enterprise auth conformance tests..."
echo ""

# Use public npm registry for conformance package
# Run the cross-app-access-complete-flow scenario which tests SEP-990
npm_config_registry=https://registry.npmjs.org \
  npx -y @modelcontextprotocol/conformance@0.1.14 client \
    --command 'uv run --frozen python .github/actions/conformance/client.py' \
    --scenario auth/cross-app-access-complete-flow

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Enterprise auth conformance tests PASSED!"
else
    echo "❌ Enterprise auth conformance tests FAILED (exit code: $EXIT_CODE)"
    echo ""
    echo "Common issues:"
    echo "  - Node.js version too old (need >= 18)"
    echo "  - Dependencies not synced (run: uv sync --frozen --all-extras --package mcp)"
    echo "  - Network issues accessing npm registry"
fi

exit $EXIT_CODE
