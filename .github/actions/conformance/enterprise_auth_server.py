#!/usr/bin/env python3
"""Enterprise Auth Mock Server for Conformance Testing

This server provides:
1. Mock IdP token exchange endpoint (RFC 8693)
2. MCP OAuth token endpoint (RFC 7523)
3. Protected MCP tools endpoint
4. OAuth metadata endpoint

Run on port 3002 to avoid conflicts with everything-server.
"""

import asyncio
import json
import logging
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI, Form, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from uvicorn import Config, Server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Generate RSA key pair for JWT signing
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_KEY = PRIVATE_KEY.public_key()

# Server configuration
IDP_ISSUER = "https://conformance-idp.example.com"
MCP_SERVER_ISSUER = "https://conformance-mcp.example.com"
MCP_SERVER_RESOURCE = "https://conformance-mcp.example.com"

# In-memory storage
ACCESS_TOKENS: dict[str, dict[str, Any]] = {}

app = FastAPI()

# Security
security = HTTPBearer(auto_error=False)


def create_test_id_token(subject: str = "test-user@example.com", client_id: str = "test-client") -> str:
    """Create a test ID token."""
    now = datetime.now(timezone.utc)
    claims = {
        "iss": IDP_ISSUER,
        "sub": subject,
        "aud": client_id,
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "iat": int(now.timestamp()),
        "email": subject,
    }
    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256")


def create_id_jag(
    subject: str,
    audience: str,
    resource: str,
    client_id: str,
    scope: str | None = None,
) -> str:
    """Create an ID-JAG token."""
    now = datetime.now(timezone.utc)
    claims = {
        "jti": str(uuid.uuid4()),
        "iss": IDP_ISSUER,
        "sub": subject,
        "aud": audience,
        "resource": resource,
        "client_id": client_id,
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "iat": int(now.timestamp()),
    }
    if scope:
        claims["scope"] = scope

    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256", headers={"typ": "oauth-id-jag+jwt"})


def verify_id_token(id_token: str) -> dict[str, Any]:
    """Verify and decode an ID token."""
    try:
        claims = jwt.decode(id_token, PUBLIC_KEY, algorithms=["RS256"], options={"verify_aud": False})
        return claims
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=400, detail=f"Invalid ID token: {e}") from e


def verify_id_jag(id_jag: str) -> dict[str, Any]:
    """Verify and decode an ID-JAG token."""
    try:
        header = jwt.get_unverified_header(id_jag)
        if header.get("typ") != "oauth-id-jag+jwt":
            raise HTTPException(status_code=400, detail="Invalid ID-JAG type")
        claims = jwt.decode(id_jag, PUBLIC_KEY, algorithms=["RS256"], options={"verify_aud": False})
        return claims
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=400, detail=f"Invalid ID-JAG: {e}") from e


# OAuth Metadata Endpoint
@app.get("/.well-known/oauth-authorization-server")
async def oauth_metadata() -> JSONResponse:
    """OAuth 2.0 Authorization Server Metadata (RFC 8414)."""
    metadata = {
        "issuer": MCP_SERVER_ISSUER,
        "token_endpoint": "http://localhost:3002/oauth/token",
        "grant_types_supported": ["urn:ietf:params:oauth:grant-type:jwt-bearer", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post", "none"],
    }
    return JSONResponse(metadata)


# Token Exchange Endpoint (IdP)
@app.post("/token-exchange")
async def token_exchange(
    grant_type: str = Form(...),
    requested_token_type: str = Form(...),
    audience: str = Form(...),
    resource: str = Form(...),
    subject_token: str = Form(...),
    subject_token_type: str = Form(...),
    scope: str | None = Form(None),
    client_id: str | None = Form(None),
    client_secret: str | None = Form(None),
) -> JSONResponse:
    """RFC 8693 Token Exchange endpoint."""
    logger.info(f"Token exchange request: grant_type={grant_type}, subject_token_type={subject_token_type}")

    if grant_type != "urn:ietf:params:oauth:grant-type:token-exchange":
        return JSONResponse(
            status_code=400,
            content={"error": "unsupported_grant_type", "error_description": "Only token-exchange grant supported"},
        )

    if requested_token_type != "urn:ietf:params:oauth:token-type:id-jag":
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_request",
                "error_description": f"Unsupported token type: {requested_token_type}",
            },
        )

    # Extract subject based on token type
    if subject_token_type == "urn:ietf:params:oauth:token-type:id_token":
        id_token_claims = verify_id_token(subject_token)
        subject = id_token_claims["sub"]
    elif subject_token_type == "urn:ietf:params:oauth:token-type:saml2":
        # For SAML, extract from mock data
        import base64

        try:
            saml_data = json.loads(base64.b64decode(subject_token))
            subject = saml_data.get("subject", "saml-user@example.com")
        except Exception:
            subject = "saml-user@example.com"
    else:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_request",
                "error_description": f"Unsupported subject token type: {subject_token_type}",
            },
        )

    # Create ID-JAG
    id_jag = create_id_jag(
        subject=subject,
        audience=audience,
        resource=resource,
        client_id=client_id or "test-client",
        scope=scope,
    )

    response = {
        "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
        "access_token": id_jag,
        "token_type": "N_A",
        "expires_in": 300,
    }
    if scope:
        response["scope"] = scope

    logger.info("Token exchange successful")
    return JSONResponse(response)


# JWT Bearer Grant Endpoint (MCP Server)
@app.post("/oauth/token")
async def jwt_bearer_grant(
    grant_type: str = Form(...),
    assertion: str = Form(...),
    client_id: str | None = Form(None),
    client_secret: str | None = Form(None),
) -> JSONResponse:
    """RFC 7523 JWT Bearer Grant endpoint."""
    logger.info(f"JWT bearer grant request: grant_type={grant_type}")

    if grant_type != "urn:ietf:params:oauth:grant-type:jwt-bearer":
        return JSONResponse(
            status_code=400,
            content={"error": "unsupported_grant_type", "error_description": "Only jwt-bearer grant supported"},
        )

    # Verify ID-JAG
    id_jag_claims = verify_id_jag(assertion)

    # Create access token
    access_token = secrets.token_urlsafe(32)
    expires_in = 3600

    # Store token info
    ACCESS_TOKENS[access_token] = {
        "subject": id_jag_claims["sub"],
        "client_id": id_jag_claims.get("client_id"),
        "scope": id_jag_claims.get("scope"),
        "expires_at": time.time() + expires_in,
    }

    response = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
    }
    if id_jag_claims.get("scope"):
        response["scope"] = id_jag_claims["scope"]

    logger.info("JWT bearer grant successful")
    return JSONResponse(response)


# MCP Endpoints (protected by access token)
@app.get("/mcp")
async def mcp_root() -> JSONResponse:
    """MCP root endpoint - returns basic info."""
    return JSONResponse({"server": "enterprise-auth-test-server", "version": "1.0"})


@app.post("/mcp")
async def mcp_jsonrpc(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> JSONResponse:
    """MCP JSON-RPC endpoint."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authorization")

    token = credentials.credentials
    if token not in ACCESS_TOKENS:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    token_info = ACCESS_TOKENS[token]
    if token_info["expires_at"] < time.time():
        del ACCESS_TOKENS[token]
        raise HTTPException(status_code=401, detail="Token expired")

    # Return a simple MCP response
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "enterprise-auth-test-server", "version": "1.0"},
            },
        }
    )


# Helper endpoint to get test ID token
@app.get("/test/id-token")
async def get_test_id_token(subject: str = "test-user@example.com", client_id: str = "test-client") -> JSONResponse:
    """Get a test ID token for conformance testing."""
    id_token = create_test_id_token(subject, client_id)
    return JSONResponse({"id_token": id_token})


@app.get("/test/context")
async def get_test_context() -> JSONResponse:
    """Get complete test context for conformance testing."""
    id_token = create_test_id_token()

    # Create mock SAML assertion
    import base64

    saml_data = {
        "issuer": IDP_ISSUER,
        "subject": "saml-user@example.com",
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }
    saml_assertion = base64.b64encode(json.dumps(saml_data).encode()).decode()

    context = {
        "id_token": id_token,
        "saml_assertion": saml_assertion,
        "idp_token_endpoint": "http://localhost:3002/token-exchange",
        "mcp_server_auth_issuer": MCP_SERVER_ISSUER,
        "mcp_server_resource_id": MCP_SERVER_RESOURCE,
        "client_id": "test-client",
        "scope": "mcp:tools mcp:resources",
    }

    return JSONResponse(context)


async def run_server(port: int = 3002) -> None:
    """Run the mock server."""
    config = Config(app=app, host="0.0.0.0", port=port, log_level="info")
    server = Server(config)
    logger.info(f"Starting Enterprise Auth Mock Server on port {port}")
    logger.info(f"Token Exchange endpoint: http://localhost:{port}/token-exchange")
    logger.info(f"JWT Bearer Grant endpoint: http://localhost:{port}/oauth/token")
    logger.info(f"MCP endpoint: http://localhost:{port}/mcp")
    logger.info(f"OAuth metadata: http://localhost:{port}/.well-known/oauth-authorization-server")
    logger.info(f"Test context: http://localhost:{port}/test/context")
    await server.serve()


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3002
    asyncio.run(run_server(port))
