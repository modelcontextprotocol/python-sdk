# Authentication

The MCP Python SDK implements OAuth 2.1 resource server functionality, allowing servers to validate tokens and protect resources. This follows the MCP authorization specification and RFC 9728.

## OAuth 2.1 architecture

MCP uses a three-party OAuth model:

- **Authorization Server (AS)** - Handles user authentication and token issuance
- **Resource Server (RS)** - Your MCP server that validates tokens  
- **Client** - Applications that access protected MCP resources

## Basic authentication setup

### Creating an authenticated server

```python
from pydantic import AnyHttpUrl
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

class SimpleTokenVerifier(TokenVerifier):
    """Simple token verifier implementation."""
    
    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify and decode an access token."""
        # In production, validate JWT signatures, check expiration, etc.
        if token.startswith("valid_"):
            return AccessToken(
                subject="user123",
                scopes=["read", "write"],
                expires_at=None,  # Non-expiring for demo
                client_id="demo_client"
            )
        return None  # Invalid token

# Create server with authentication
mcp = FastMCP(
    "Protected Weather Service",
    token_verifier=SimpleTokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl("https://auth.example.com"),
        resource_server_url=AnyHttpUrl("http://localhost:3001"),
        required_scopes=["weather:read"]
    )
)

@mcp.tool()
async def get_weather(city: str = "London") -> dict[str, str]:
    """Get weather data - requires authentication."""
    return {
        "city": city,
        "temperature": "22°C",
        "condition": "Sunny",
        "humidity": "45%"
    }
```

### Advanced token verification

```python
import jwt
import time
from typing import Optional

class JWTTokenVerifier(TokenVerifier):
    """JWT-based token verifier."""
    
    def __init__(self, public_key: str, algorithm: str = "RS256"):
        self.public_key = public_key
        self.algorithm = algorithm
    
    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify JWT token."""
        try:
            # Decode and verify JWT
            payload = jwt.decode(
                token,
                self.public_key,
                algorithms=[self.algorithm],
                options={"verify_exp": True}
            )
            
            # Extract standard claims
            subject = payload.get("sub")
            scopes = payload.get("scope", "").split()
            expires_at = payload.get("exp")
            client_id = payload.get("client_id")
            
            if not subject:
                return None
                
            return AccessToken(
                subject=subject,
                scopes=scopes,
                expires_at=expires_at,
                client_id=client_id,
                raw_token=token
            )
            
        except jwt.InvalidTokenError:
            return None
        except Exception:
            # Log error in production
            return None

# Use JWT verifier
jwt_verifier = JWTTokenVerifier(public_key="your-rsa-public-key")
mcp = FastMCP("JWT Protected Service", token_verifier=jwt_verifier)
```

## Scope-based authorization

### Protecting resources by scope

```python
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("Scoped API", token_verifier=SimpleTokenVerifier())

@mcp.tool()
async def read_data(ctx: Context[ServerSession, None]) -> dict:
    """Read data - requires 'read' scope."""
    # Access token information from context
    if hasattr(ctx.session, 'access_token'):
        token = ctx.session.access_token
        if "read" not in token.scopes:
            raise ValueError("Insufficient permissions: read scope required")
        
        await ctx.info(f"Data accessed by user: {token.subject}")
        return {"data": "sensitive information", "user": token.subject}
    
    raise ValueError("Authentication required")

@mcp.tool()  
async def write_data(data: str, ctx: Context[ServerSession, None]) -> dict:
    """Write data - requires 'write' scope."""
    if hasattr(ctx.session, 'access_token'):
        token = ctx.session.access_token
        if "write" not in token.scopes:
            raise ValueError("Insufficient permissions: write scope required")
        
        await ctx.info(f"Data written by user: {token.subject}")
        return {"status": "written", "data": data, "user": token.subject}
    
    raise ValueError("Authentication required")

@mcp.tool()
async def admin_operation(ctx: Context[ServerSession, None]) -> dict:
    """Admin operation - requires 'admin' scope."""
    if hasattr(ctx.session, 'access_token'):
        token = ctx.session.access_token
        if "admin" not in token.scopes:
            raise ValueError("Admin access required")
        
        return {"message": "Admin operation completed", "admin": token.subject}
    
    raise ValueError("Authentication required")
```

### Custom authorization decorators

```python
from functools import wraps

def require_scopes(*required_scopes):
    """Decorator to require specific scopes."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find context argument
            ctx = None
            for arg in args:
                if isinstance(arg, Context):
                    ctx = arg
                    break
            
            if not ctx:
                raise ValueError("Context required for authorization")
            
            if not hasattr(ctx.session, 'access_token'):
                raise ValueError("Authentication required")
            
            token = ctx.session.access_token
            missing_scopes = set(required_scopes) - set(token.scopes)
            
            if missing_scopes:
                raise ValueError(f"Missing required scopes: {', '.join(missing_scopes)}")
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator

@mcp.tool()
@require_scopes("user:profile", "user:email")
async def get_user_profile(user_id: str, ctx: Context) -> dict:
    """Get user profile - requires specific scopes."""
    token = ctx.session.access_token
    await ctx.info(f"Profile accessed by {token.subject} for user {user_id}")
    
    return {
        "user_id": user_id,
        "name": "John Doe",
        "email": "john@example.com",
        "accessed_by": token.subject
    }
```

## Token introspection

### OAuth token introspection

```python
import aiohttp
import json

class IntrospectionTokenVerifier(TokenVerifier):
    """Token verifier using OAuth introspection endpoint."""
    
    def __init__(self, introspection_url: str, client_id: str, client_secret: str):
        self.introspection_url = introspection_url
        self.client_id = client_id
        self.client_secret = client_secret
    
    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify token using introspection endpoint."""
        try:
            async with aiohttp.ClientSession() as session:
                # Prepare introspection request
                data = {
                    "token": token,
                    "token_type_hint": "access_token"
                }
                
                auth = aiohttp.BasicAuth(self.client_id, self.client_secret)
                
                async with session.post(
                    self.introspection_url,
                    data=data,
                    auth=auth
                ) as response:
                    if response.status != 200:
                        return None
                    
                    result = await response.json()
                    
                    # Check if token is active
                    if not result.get("active", False):
                        return None
                    
                    # Extract token information
                    return AccessToken(
                        subject=result.get("sub"),
                        scopes=result.get("scope", "").split(),
                        expires_at=result.get("exp"),
                        client_id=result.get("client_id"),
                        raw_token=token
                    )
                    
        except Exception:
            # Log error in production
            return None

# Use introspection verifier
introspection_verifier = IntrospectionTokenVerifier(
    introspection_url="https://auth.example.com/oauth/introspect",
    client_id="mcp_server",
    client_secret="server_secret"
)

mcp = FastMCP("Introspection Server", token_verifier=introspection_verifier)
```

## Database-backed authorization

### User and permission management

```python
from dataclasses import dataclass
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

@dataclass
class User:
    id: str
    username: str
    roles: list[str]
    permissions: list[str]

class AuthDatabase:
    """Mock authentication database."""
    
    def __init__(self):
        self.users = {
            "user123": User("user123", "alice", ["user"], ["read", "write"]),
            "admin456": User("admin456", "admin", ["admin"], ["read", "write", "delete", "admin"])
        }
    
    async def get_user(self, user_id: str) -> User | None:
        return self.users.get(user_id)
    
    async def verify_token(self, token: str) -> User | None:
        # Simple token format: "token_userid"
        if token.startswith("token_"):
            user_id = token[6:]  # Remove "token_" prefix
            return await self.get_user(user_id)
        return None

@dataclass
class AppContext:
    auth_db: AuthDatabase

@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    auth_db = AuthDatabase()
    yield AppContext(auth_db=auth_db)

class DatabaseTokenVerifier(TokenVerifier):
    """Token verifier using database lookup."""
    
    def __init__(self, auth_db: AuthDatabase):
        self.auth_db = auth_db
    
    async def verify_token(self, token: str) -> AccessToken | None:
        user = await self.auth_db.verify_token(token)
        if user:
            return AccessToken(
                subject=user.id,
                scopes=user.permissions,
                expires_at=None,
                client_id="database_client"
            )
        return None

# Create server with database authentication
auth_db = AuthDatabase()
mcp = FastMCP(
    "Database Auth Server",
    lifespan=app_lifespan,
    token_verifier=DatabaseTokenVerifier(auth_db)
)

@mcp.tool()
async def get_user_info(
    user_id: str, 
    ctx: Context[ServerSession, AppContext]
) -> dict:
    """Get user information - requires authentication."""
    # Verify user is authenticated
    if not hasattr(ctx.session, 'access_token'):
        raise ValueError("Authentication required")
    
    token = ctx.session.access_token
    auth_db = ctx.request_context.lifespan_context.auth_db
    
    # Check if user can access this information
    if token.subject != user_id and "admin" not in token.scopes:
        raise ValueError("Insufficient permissions")
    
    user = await auth_db.get_user(user_id)
    if not user:
        raise ValueError("User not found")
    
    return {
        "user_id": user.id,
        "username": user.username,
        "roles": user.roles,
        "permissions": user.permissions
    }
```

## Error handling and security

### Authentication error handling

```python
@mcp.tool()
async def secure_operation(data: str, ctx: Context) -> dict:
    """Secure operation with comprehensive error handling."""
    try:
        # Check authentication
        if not hasattr(ctx.session, 'access_token'):
            await ctx.warning("Unauthenticated access attempt")
            raise ValueError("Authentication required")
        
        token = ctx.session.access_token
        
        # Check token expiration
        if token.expires_at and token.expires_at < time.time():
            await ctx.warning(f"Expired token used by {token.subject}")
            raise ValueError("Token expired")
        
        # Check required scopes
        required_scopes = ["secure:access"]
        missing_scopes = set(required_scopes) - set(token.scopes)
        if missing_scopes:
            await ctx.warning(f"Insufficient scopes for {token.subject}: missing {missing_scopes}")
            raise ValueError(f"Missing required scopes: {', '.join(missing_scopes)}")
        
        # Log successful access
        await ctx.info(f"Secure operation accessed by {token.subject}")
        
        # Perform secure operation
        return {
            "result": f"Processed: {data}",
            "user": token.subject,
            "timestamp": time.time()
        }
        
    except ValueError as e:
        await ctx.error(f"Authorization failed: {e}")
        raise
    except Exception as e:
        await ctx.error(f"Unexpected error in secure operation: {e}")
        raise ValueError("Internal server error")
```

### Rate limiting by user

```python
import time
from collections import defaultdict

class RateLimiter:
    """Simple rate limiter by user."""
    
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.requests = defaultdict(list)
    
    def is_allowed(self, user_id: str) -> bool:
        """Check if user is within rate limits."""
        now = time.time()
        minute_ago = now - 60
        
        # Clean old requests
        self.requests[user_id] = [
            req_time for req_time in self.requests[user_id]
            if req_time > minute_ago
        ]
        
        # Check if under limit
        if len(self.requests[user_id]) >= self.requests_per_minute:
            return False
        
        # Record this request
        self.requests[user_id].append(now)
        return True

# Global rate limiter
rate_limiter = RateLimiter(requests_per_minute=100)

def rate_limited(func):
    """Decorator to apply rate limiting."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Find context
        ctx = None
        for arg in args:
            if isinstance(arg, Context):
                ctx = arg
                break
        
        if ctx and hasattr(ctx.session, 'access_token'):
            user_id = ctx.session.access_token.subject
            
            if not rate_limiter.is_allowed(user_id):
                await ctx.warning(f"Rate limit exceeded for user {user_id}")
                raise ValueError("Rate limit exceeded")
        
        return await func(*args, **kwargs)
    
    return wrapper

@mcp.tool()
@rate_limited
async def api_call(endpoint: str, ctx: Context) -> dict:
    """Rate-limited API call."""
    token = ctx.session.access_token
    await ctx.info(f"API call to {endpoint} by {token.subject}")
    
    return {
        "endpoint": endpoint,
        "user": token.subject,
        "result": "API response data"
    }
```

## Testing authentication

### Unit testing with mock tokens

```python
import pytest
from unittest.mock import Mock, AsyncMock

@pytest.mark.asyncio
async def test_authenticated_tool():
    """Test tool with authentication."""
    # Create mock context with token
    mock_ctx = Mock()
    mock_ctx.session = Mock()
    mock_ctx.session.access_token = AccessToken(
        subject="test_user",
        scopes=["read", "write"],
        expires_at=None,
        client_id="test_client"
    )
    mock_ctx.info = AsyncMock()
    
    # Test authenticated function
    @require_scopes("read")
    async def test_function(data: str, ctx: Context) -> dict:
        await ctx.info("Function called")
        return {"data": data, "user": ctx.session.access_token.subject}
    
    result = await test_function("test", mock_ctx)
    
    assert result["data"] == "test"
    assert result["user"] == "test_user"
    mock_ctx.info.assert_called_once()

@pytest.mark.asyncio
async def test_insufficient_scopes():
    """Test scope enforcement."""
    mock_ctx = Mock()
    mock_ctx.session = Mock()
    mock_ctx.session.access_token = AccessToken(
        subject="test_user",
        scopes=["read"],  # Missing 'write' scope
        expires_at=None,
        client_id="test_client"
    )
    
    @require_scopes("read", "write")
    async def test_function(ctx: Context) -> dict:
        return {"result": "success"}
    
    with pytest.raises(ValueError, match="Missing required scopes"):
        await test_function(mock_ctx)
```

## Production considerations

### Security best practices

- **Validate all tokens** - Never trust client-provided tokens
- **Use HTTPS only** - All authentication must happen over secure connections
- **Implement proper logging** - Log authentication events for security monitoring
- **Rate limiting** - Prevent abuse with per-user rate limits
- **Token expiration** - Use short-lived tokens with refresh capabilities
- **Scope minimization** - Grant minimum required permissions

### Performance optimization

- **Token caching** - Cache validated tokens to reduce verification overhead
- **Connection pooling** - Reuse HTTP connections for introspection
- **Database optimization** - Index user/permission lookup tables
- **Async operations** - Use async/await for all I/O operations

### Monitoring and alerting

```python
import logging

# Configure security logger
security_logger = logging.getLogger("security")

@mcp.tool()
async def monitored_operation(ctx: Context) -> dict:
    """Operation with security monitoring."""
    if not hasattr(ctx.session, 'access_token'):
        security_logger.warning("Unauthenticated access attempt")
        raise ValueError("Authentication required")
    
    token = ctx.session.access_token
    
    # Log successful access
    security_logger.info(f"Secure access by {token.subject} with scopes {token.scopes}")
    
    # Check for suspicious patterns
    if "admin" in token.scopes and token.subject != "admin_user":
        security_logger.warning(f"Non-admin user {token.subject} has admin scopes")
    
    return {"status": "success", "user": token.subject}
```

## Next steps

- **[Server deployment](running-servers.md)** - Deploy authenticated servers
- **[Client authentication](oauth-clients.md)** - Implement client-side OAuth
- **[Advanced security](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)** - Full MCP authorization spec
- **[Monitoring](progress-logging.md)** - Security logging and monitoring