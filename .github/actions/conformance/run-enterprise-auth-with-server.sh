#!/bin/bash
set -e

# Enterprise Auth Full Conformance Test with Mock Server
# This script:
# 1. Starts the enterprise auth mock server (IdP + OAuth endpoints)
# 2. Fetches test context from the server
# 3. Runs all enterprise auth conformance scenarios
# 4. Cleans up servers on exit

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../../.."

MOCK_SERVER_PORT=3002
MOCK_SERVER_URL="http://localhost:${MOCK_SERVER_PORT}"

echo "==================================================================="
echo "  Enterprise Auth Conformance Tests with Mock Server (SEP-990)"
echo "==================================================================="
echo ""

# Function to cleanup servers
cleanup() {
    echo ""
    echo "Cleaning up servers..."
    if [ -n "$MOCK_SERVER_PID" ]; then
        kill $MOCK_SERVER_PID 2>/dev/null || true
        wait $MOCK_SERVER_PID 2>/dev/null || true
        echo "✓ Mock server stopped"
    fi
}

trap cleanup EXIT

# Start enterprise auth mock server
echo "Starting Enterprise Auth Mock Server on port ${MOCK_SERVER_PORT}..."
uv run --frozen python "$SCRIPT_DIR/enterprise_auth_server.py" $MOCK_SERVER_PORT > /tmp/enterprise_auth_server.log 2>&1 &
MOCK_SERVER_PID=$!

# Wait for mock server to be ready
echo "Waiting for mock server to be ready..."
MAX_RETRIES=30
RETRY_COUNT=0
while ! curl -s "${MOCK_SERVER_URL}/test/context" > /dev/null 2>&1; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "✗ Mock server failed to start after ${MAX_RETRIES} retries" >&2
        echo "Server log:"
        cat /tmp/enterprise_auth_server.log
        exit 1
    fi
    sleep 0.5
done

echo "✓ Mock server ready at ${MOCK_SERVER_URL}"
echo ""

# Fetch test context from server
echo "Fetching test context from mock server..."
export MCP_CONFORMANCE_CONTEXT=$(curl -s "${MOCK_SERVER_URL}/test/context")

if [ -z "$MCP_CONFORMANCE_CONTEXT" ]; then
    echo "✗ Failed to fetch test context" >&2
    exit 1
fi

echo "✓ Test context retrieved"
echo ""

# Display server info
echo "Server Endpoints:"
echo "  - Token Exchange (IdP):  ${MOCK_SERVER_URL}/token-exchange"
echo "  - OAuth Token (MCP):     ${MOCK_SERVER_URL}/oauth/token"
echo "  - MCP Endpoint:          ${MOCK_SERVER_URL}/mcp"
echo "  - OAuth Metadata:        ${MOCK_SERVER_URL}/.well-known/oauth-authorization-server"
echo ""

# Run conformance scenarios
echo "==================================================================="
echo "  Running Conformance Test Scenarios"
echo "==================================================================="
echo ""

# Test 1: ID-JAG Validation
echo "--- Test 1: ID-JAG Token Validation ---"
export MCP_CONFORMANCE_SCENARIO="auth/enterprise-id-jag-validation"
if uv run --frozen python "$SCRIPT_DIR/client.py" "${MOCK_SERVER_URL}/mcp" 2>&1 | tee /tmp/test1.log | grep -q "ID-JAG validation completed successfully"; then
    echo "✓ ID-JAG validation PASSED"
    TEST1_PASS=true
else
    echo "✗ ID-JAG validation FAILED"
    echo "Log output:"
    cat /tmp/test1.log | tail -20
    TEST1_PASS=false
fi
echo ""

# Test 2: OIDC ID Token Exchange Flow
echo "--- Test 2: OIDC ID Token Exchange Flow ---"
export MCP_CONFORMANCE_SCENARIO="auth/enterprise-token-exchange"
if uv run --frozen python "$SCRIPT_DIR/client.py" "${MOCK_SERVER_URL}/mcp" 2>&1 | tee /tmp/test2.log | grep -q "Enterprise auth flow completed successfully"; then
    echo "✓ OIDC token exchange PASSED"
    TEST2_PASS=true
else
    echo "✗ OIDC token exchange FAILED"
    echo "Log output:"
    cat /tmp/test2.log | tail -20
    TEST2_PASS=false
fi
echo ""

# Test 3: SAML Assertion Exchange Flow
echo "--- Test 3: SAML Assertion Exchange Flow ---"
export MCP_CONFORMANCE_SCENARIO="auth/enterprise-saml-exchange"
if uv run --frozen python "$SCRIPT_DIR/client.py" "${MOCK_SERVER_URL}/mcp" 2>&1 | tee /tmp/test3.log | grep -q "SAML enterprise auth flow completed successfully"; then
    echo "✓ SAML assertion exchange PASSED"
    TEST3_PASS=true
else
    echo "✗ SAML assertion exchange FAILED"
    echo "Log output:"
    cat /tmp/test3.log | tail -20
    TEST3_PASS=false
fi
echo ""

# Summary
echo "==================================================================="
echo "  Test Results Summary"
echo "==================================================================="
echo ""

TESTS_PASSED=0
TESTS_FAILED=0

if [ "$TEST1_PASS" = true ]; then
    echo "✓ ID-JAG Validation"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    echo "✗ ID-JAG Validation"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi

if [ "$TEST2_PASS" = true ]; then
    echo "✓ OIDC Token Exchange"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    echo "✗ OIDC Token Exchange"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi

if [ "$TEST3_PASS" = true ]; then
    echo "✓ SAML Assertion Exchange"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    echo "✗ SAML Assertion Exchange"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi

echo ""
echo "Total: ${TESTS_PASSED}/3 passed, ${TESTS_FAILED}/3 failed"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo "🎉 All enterprise auth conformance tests PASSED!"
    exit 0
else
    echo "❌ Some tests failed. Check logs above for details."
    exit 1
fi
