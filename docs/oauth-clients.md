# OAuth for clients

Learn how to implement OAuth 2.1 authentication in MCP clients to securely connect to authenticated servers.

## Overview

OAuth for MCP clients enables:

- **Secure authentication** - Industry-standard OAuth 2.1 flows
- **Token management** - Automatic token refresh and storage
- **Multiple providers** - Support for various OAuth providers
- **Credential security** - Secure storage and transmission of credentials

## Basic OAuth client

### Simple OAuth client

```python
"""
MCP client with OAuth 2.1 authentication.
"""

import asyncio
from mcp import ClientSession
from mcp.client.oauth import OAuthClient, OAuthConfig
from mcp.client.streamable_http import streamablehttp_client

async def oauth_client_example():
    """Connect to MCP server with OAuth authentication."""
    
    # Configure OAuth
    oauth_config = OAuthConfig(
        client_id="your-client-id",
        client_secret="your-client-secret",
        authorization_url="https://auth.example.com/oauth/authorize",
        token_url="https://auth.example.com/oauth/token",
        redirect_uri="http://localhost:8080/callback",
        scope="mcp:read mcp:write"
    )
    
    # Create OAuth client
    oauth_client = OAuthClient(oauth_config)
    
    # Authenticate (will open browser for authorization)
    await oauth_client.authenticate()
    
    # Connect to MCP server with OAuth
    server_url = "https://api.example.com/mcp"
    
    async with streamablehttp_client(server_url) as (read, write, session_info):
        # Add OAuth headers to requests
        oauth_client.add_auth_headers(session_info.headers)
        
        async with ClientSession(read, write) as session:
            # Initialize with authentication
            await session.initialize()
            
            # Now you can make authenticated requests
            tools = await session.list_tools()
            print(f"Available tools: {[tool.name for tool in tools.tools]}")
            
            # Call tools with authentication
            result = await session.call_tool("protected_tool", {"data": "test"})
            if result.content:
                content = result.content[0]
                if hasattr(content, 'text'):
                    print(f"Result: {content.text}")

if __name__ == "__main__":
    asyncio.run(oauth_client_example())
```

## OAuth configuration

### Configuration options

```python
"""
Comprehensive OAuth configuration.
"""

from mcp.client.oauth import OAuthConfig, OAuthFlow

# Standard authorization code flow
standard_config = OAuthConfig(
    client_id="your-client-id",
    client_secret="your-client-secret",
    authorization_url="https://auth.example.com/oauth/authorize",
    token_url="https://auth.example.com/oauth/token",
    redirect_uri="http://localhost:8080/callback",
    scope="mcp:read mcp:write mcp:admin",
    flow=OAuthFlow.AUTHORIZATION_CODE
)

# PKCE flow for public clients
pkce_config = OAuthConfig(
    client_id="public-client-id",
    authorization_url="https://auth.example.com/oauth/authorize",
    token_url="https://auth.example.com/oauth/token",
    redirect_uri="http://localhost:8080/callback",
    scope="mcp:read mcp:write",
    flow=OAuthFlow.AUTHORIZATION_CODE_PKCE,
    code_challenge_method="S256"
)

# Client credentials flow for service-to-service
service_config = OAuthConfig(
    client_id="service-client-id",
    client_secret="service-client-secret",
    token_url="https://auth.example.com/oauth/token",
    scope="mcp:service",
    flow=OAuthFlow.CLIENT_CREDENTIALS
)

# Device code flow for CLI applications
device_config = OAuthConfig(
    client_id="device-client-id",
    authorization_url="https://auth.example.com/device/authorize",
    token_url="https://auth.example.com/oauth/token",
    device_authorization_url="https://auth.example.com/device/code",
    scope="mcp:read mcp:write",
    flow=OAuthFlow.DEVICE_CODE
)
```

### Environment configuration

Store OAuth credentials securely:

```bash
# .env file for OAuth configuration
OAUTH_CLIENT_ID=your-client-id
OAUTH_CLIENT_SECRET=your-client-secret
OAUTH_AUTHORIZATION_URL=https://auth.example.com/oauth/authorize
OAUTH_TOKEN_URL=https://auth.example.com/oauth/token
OAUTH_REDIRECT_URI=http://localhost:8080/callback
OAUTH_SCOPE=mcp:read mcp:write
```

Load from environment:

```python
import os
from mcp.client.oauth import OAuthConfig

def load_oauth_config() -> OAuthConfig:
    """Load OAuth configuration from environment."""
    return OAuthConfig(
        client_id=os.getenv("OAUTH_CLIENT_ID"),
        client_secret=os.getenv("OAUTH_CLIENT_SECRET"),
        authorization_url=os.getenv("OAUTH_AUTHORIZATION_URL"),
        token_url=os.getenv("OAUTH_TOKEN_URL"),
        redirect_uri=os.getenv("OAUTH_REDIRECT_URI"),
        scope=os.getenv("OAUTH_SCOPE", "mcp:read")
    )
```

## Token management

### Automatic token refresh

```python
"""
OAuth client with automatic token refresh.
"""

import asyncio
import json
from pathlib import Path
from mcp.client.oauth import OAuthClient, TokenStore

class FileTokenStore(TokenStore):
    """Token store that persists tokens to disk."""
    
    def __init__(self, token_file: str = ".oauth_tokens.json"):
        self.token_file = Path(token_file)
    
    async def save_tokens(self, tokens: dict):
        """Save tokens to file."""
        with open(self.token_file, 'w') as f:
            json.dump(tokens, f, indent=2)
    
    async def load_tokens(self) -> dict | None:
        """Load tokens from file."""
        if not self.token_file.exists():
            return None
        
        try:
            with open(self.token_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    
    async def clear_tokens(self):
        """Clear stored tokens."""
        if self.token_file.exists():
            self.token_file.unlink()

class AutoRefreshOAuthClient(OAuthClient):
    """OAuth client with automatic token refresh."""
    
    def __init__(self, config: OAuthConfig, token_store: TokenStore):
        super().__init__(config)
        self.token_store = token_store
        self._tokens = None
    
    async def authenticate(self):
        """Authenticate with token refresh support."""
        # Try to load existing tokens
        self._tokens = await self.token_store.load_tokens()
        
        if self._tokens:
            # Check if tokens are still valid
            if await self._are_tokens_valid():
                return
            
            # Try to refresh tokens
            if await self._refresh_tokens():
                return
        
        # Perform fresh authentication
        await super().authenticate()
        
        # Save new tokens
        if self._tokens:
            await self.token_store.save_tokens(self._tokens)
    
    async def _are_tokens_valid(self) -> bool:
        """Check if current tokens are valid."""
        if not self._tokens or 'access_token' not in self._tokens:
            return False
        
        # Check expiration if available
        if 'expires_at' in self._tokens:
            import time
            return time.time() < self._tokens['expires_at']
        
        return True
    
    async def _refresh_tokens(self) -> bool:
        """Refresh access tokens using refresh token."""
        if not self._tokens or 'refresh_token' not in self._tokens:
            return False
        
        try:
            # Make refresh request
            refresh_data = {
                'grant_type': 'refresh_token',
                'refresh_token': self._tokens['refresh_token'],
                'client_id': self.config.client_id
            }
            
            if self.config.client_secret:
                refresh_data['client_secret'] = self.config.client_secret
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.config.token_url,
                    data=refresh_data
                ) as response:
                    if response.status == 200:
                        new_tokens = await response.json()
                        
                        # Update tokens
                        self._tokens.update(new_tokens)
                        
                        # Calculate expiration
                        if 'expires_in' in new_tokens:
                            import time
                            self._tokens['expires_at'] = time.time() + new_tokens['expires_in']
                        
                        # Save updated tokens
                        await self.token_store.save_tokens(self._tokens)
                        return True
            
            return False
            
        except Exception:
            return False
    
    def get_auth_headers(self) -> dict[str, str]:
        """Get authentication headers for requests."""
        if not self._tokens or 'access_token' not in self._tokens:
            raise RuntimeError("Not authenticated")
        
        return {
            'Authorization': f"Bearer {self._tokens['access_token']}"
        }

# Usage example
async def auto_refresh_example():
    """Example using auto-refresh OAuth client."""
    config = load_oauth_config()
    token_store = FileTokenStore()
    oauth_client = AutoRefreshOAuthClient(config, token_store)
    
    # Authenticate (will use stored tokens if valid)
    await oauth_client.authenticate()
    
    # Use client with automatic token refresh
    server_url = "https://api.example.com/mcp"
    
    async with streamablehttp_client(server_url) as (read, write, session_info):
        # Add auth headers
        session_info.headers.update(oauth_client.get_auth_headers())
        
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # Make authenticated requests
            tools = await session.list_tools()
            print(f"Available tools: {len(tools.tools)}")

if __name__ == "__main__":
    asyncio.run(auto_refresh_example())
```

## OAuth flows

### Authorization code flow

```python
"""
Standard authorization code flow implementation.
"""

import asyncio
import webbrowser
from urllib.parse import urlparse, parse_qs
from aiohttp import web
import aiohttp

class AuthorizationCodeFlow:
    """OAuth 2.1 Authorization Code Flow."""
    
    def __init__(self, config: OAuthConfig):
        self.config = config
        self.auth_code = None
        self.auth_error = None
    
    async def authenticate(self) -> dict:
        """Perform authorization code flow."""
        # Start local callback server
        app = web.Application()
        app.router.add_get('/callback', self._handle_callback)
        
        runner = web.AppRunner(app)
        await runner.setup()
        
        # Extract port from redirect URI
        parsed_uri = urlparse(self.config.redirect_uri)
        port = parsed_uri.port or 8080
        
        site = web.TCPSite(runner, 'localhost', port)
        await site.start()
        
        try:
            # Generate authorization URL
            auth_url = self._build_auth_url()
            
            # Open browser for user authorization
            print(f"Opening browser for authorization: {auth_url}")
            webbrowser.open(auth_url)
            
            # Wait for callback
            await self._wait_for_callback()
            
            if self.auth_error:
                raise RuntimeError(f"Authorization failed: {self.auth_error}")
            
            if not self.auth_code:
                raise RuntimeError("No authorization code received")
            
            # Exchange code for tokens
            return await self._exchange_code_for_tokens()
            
        finally:
            await runner.cleanup()
    
    def _build_auth_url(self) -> str:
        """Build authorization URL."""
        from urllib.parse import urlencode
        import secrets
        
        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)
        
        params = {
            'response_type': 'code',
            'client_id': self.config.client_id,
            'redirect_uri': self.config.redirect_uri,
            'scope': self.config.scope,
            'state': state
        }
        
        return f"{self.config.authorization_url}?{urlencode(params)}"
    
    async def _handle_callback(self, request):
        """Handle OAuth callback."""
        # Extract parameters
        code = request.query.get('code')
        error = request.query.get('error')
        
        if error:
            self.auth_error = error
        else:
            self.auth_code = code
        
        # Return success page
        return web.Response(
            text="Authorization complete. You can close this window.",
            content_type='text/html'
        )
    
    async def _wait_for_callback(self):
        """Wait for OAuth callback."""
        timeout = 300  # 5 minutes
        interval = 0.1
        
        for _ in range(int(timeout / interval)):
            if self.auth_code or self.auth_error:
                return
            await asyncio.sleep(interval)
        
        raise TimeoutError("Authorization timeout")
    
    async def _exchange_code_for_tokens(self) -> dict:
        """Exchange authorization code for tokens."""
        token_data = {
            'grant_type': 'authorization_code',
            'code': self.auth_code,
            'redirect_uri': self.config.redirect_uri,
            'client_id': self.config.client_id
        }
        
        if self.config.client_secret:
            token_data['client_secret'] = self.config.client_secret
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.config.token_url,
                data=token_data
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise RuntimeError(f"Token exchange failed: {error_text}")
                
                tokens = await response.json()
                
                # Add expiration timestamp
                if 'expires_in' in tokens:
                    import time
                    tokens['expires_at'] = time.time() + tokens['expires_in']
                
                return tokens
```

### Client credentials flow

```python
"""
Client credentials flow for service-to-service authentication.
"""

async def client_credentials_flow(config: OAuthConfig) -> dict:
    """Perform client credentials flow."""
    if not config.client_secret:
        raise ValueError("Client secret required for client credentials flow")
    
    token_data = {
        'grant_type': 'client_credentials',
        'client_id': config.client_id,
        'client_secret': config.client_secret,
        'scope': config.scope
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            config.token_url,
            data=token_data
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise RuntimeError(f"Client credentials flow failed: {error_text}")
            
            tokens = await response.json()
            
            # Add expiration timestamp
            if 'expires_in' in tokens:
                import time
                tokens['expires_at'] = time.time() + tokens['expires_in']
            
            return tokens

# Usage example
async def service_auth_example():
    """Service-to-service authentication example."""
    config = OAuthConfig(
        client_id="service-client",
        client_secret="service-secret",
        token_url="https://auth.example.com/oauth/token",
        scope="mcp:service",
        flow=OAuthFlow.CLIENT_CREDENTIALS
    )
    
    tokens = await client_credentials_flow(config)
    
    # Use tokens for authenticated requests
    headers = {'Authorization': f"Bearer {tokens['access_token']}"}
    
    async with streamablehttp_client(
        "https://api.example.com/mcp",
        headers=headers
    ) as (read, write, session_info):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Service authenticated successfully")
```

### Device code flow

```python
"""
Device code flow for CLI and limited-input devices.
"""

async def device_code_flow(config: OAuthConfig) -> dict:
    """Perform device code flow."""
    # Request device code
    device_data = {
        'client_id': config.client_id,
        'scope': config.scope
    }
    
    async with aiohttp.ClientSession() as session:
        # Get device code
        async with session.post(
            config.device_authorization_url,
            data=device_data
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise RuntimeError(f"Device authorization failed: {error_text}")
            
            device_response = await response.json()
        
        # Display user instructions
        print(f"Visit: {device_response['verification_uri']}")
        print(f"Enter code: {device_response['user_code']}")
        print("Waiting for authorization...")
        
        # Poll for tokens
        poll_interval = device_response.get('interval', 5)
        expires_in = device_response.get('expires_in', 1800)
        device_code = device_response['device_code']
        
        import time
        start_time = time.time()
        
        while time.time() - start_time < expires_in:
            await asyncio.sleep(poll_interval)
            
            # Poll token endpoint
            poll_data = {
                'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
                'device_code': device_code,
                'client_id': config.client_id
            }
            
            async with session.post(
                config.token_url,
                data=poll_data
            ) as poll_response:
                if poll_response.status == 200:
                    tokens = await poll_response.json()
                    
                    # Add expiration timestamp
                    if 'expires_in' in tokens:
                        tokens['expires_at'] = time.time() + tokens['expires_in']
                    
                    print("Authorization successful!")
                    return tokens
                
                elif poll_response.status == 400:
                    error_response = await poll_response.json()
                    error_code = error_response.get('error')
                    
                    if error_code == 'authorization_pending':
                        continue  # Keep polling
                    elif error_code == 'slow_down':
                        poll_interval += 5  # Increase interval
                        continue
                    elif error_code in ['access_denied', 'expired_token']:
                        raise RuntimeError(f"Authorization failed: {error_code}")
        
        raise TimeoutError("Device authorization timeout")

# Usage example
async def device_auth_example():
    """Device code flow example."""
    config = OAuthConfig(
        client_id="device-client",
        authorization_url="https://auth.example.com/device/authorize",
        token_url="https://auth.example.com/oauth/token",
        device_authorization_url="https://auth.example.com/device/code",
        scope="mcp:read mcp:write",
        flow=OAuthFlow.DEVICE_CODE
    )
    
    tokens = await device_code_flow(config)
    
    # Use tokens for authenticated requests
    headers = {'Authorization': f"Bearer {tokens['access_token']}"}
    
    async with streamablehttp_client(
        "https://api.example.com/mcp",
        headers=headers
    ) as (read, write, session_info):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Device authenticated successfully")
```

## Integration examples

### OAuth with connection pooling

```python
"""
OAuth client with connection pooling for high-performance applications.
"""

import asyncio
from dataclasses import dataclass
from typing import Dict, Optional
from contextlib import asynccontextmanager

@dataclass
class AuthenticatedConnection:
    """Connection with OAuth authentication."""
    read_stream: Any
    write_stream: Any
    session: ClientSession
    tokens: Dict[str, Any]

class OAuthConnectionPool:
    """Connection pool with OAuth authentication."""
    
    def __init__(
        self,
        server_url: str,
        oauth_config: OAuthConfig,
        pool_size: int = 5
    ):
        self.server_url = server_url
        self.oauth_config = oauth_config
        self.pool_size = pool_size
        self.available_connections: asyncio.Queue = asyncio.Queue()
        self.active_connections: set = set()
        self.oauth_client = AutoRefreshOAuthClient(
            oauth_config,
            FileTokenStore()
        )
    
    async def initialize(self):
        """Initialize the connection pool."""
        # Authenticate once
        await self.oauth_client.authenticate()
        
        # Create initial connections
        for _ in range(self.pool_size):
            connection = await self._create_connection()
            if connection:
                await self.available_connections.put(connection)
    
    async def _create_connection(self) -> Optional[AuthenticatedConnection]:
        """Create an authenticated connection."""
        try:
            # Get auth headers
            headers = self.oauth_client.get_auth_headers()
            
            # Create connection with auth
            read, write, session_info = await streamablehttp_client(
                self.server_url,
                headers=headers
            ).__aenter__()
            
            # Initialize session
            session = ClientSession(read, write)
            await session.__aenter__()
            await session.initialize()
            
            return AuthenticatedConnection(
                read_stream=read,
                write_stream=write,
                session=session,
                tokens=self.oauth_client._tokens
            )
            
        except Exception as e:
            print(f"Failed to create connection: {e}")
            return None
    
    @asynccontextmanager
    async def get_connection(self):
        """Get an authenticated connection from the pool."""
        try:
            # Get available connection
            connection = await asyncio.wait_for(
                self.available_connections.get(),
                timeout=10.0
            )
            
            self.active_connections.add(connection)
            yield connection.session
            
        except asyncio.TimeoutError:
            raise RuntimeError("No connections available")
        
        finally:
            # Return connection to pool
            if connection in self.active_connections:
                self.active_connections.remove(connection)
                await self.available_connections.put(connection)
    
    async def close(self):
        """Close all connections in the pool."""
        # Close active connections
        for connection in list(self.active_connections):
            try:
                await connection.session.__aexit__(None, None, None)
            except:
                pass
        
        # Close available connections
        while not self.available_connections.empty():
            try:
                connection = self.available_connections.get_nowait()
                await connection.session.__aexit__(None, None, None)
            except:
                pass

# Usage example
async def pooled_oauth_example():
    """Example using OAuth connection pool."""
    config = load_oauth_config()
    
    pool = OAuthConnectionPool(
        "https://api.example.com/mcp",
        config,
        pool_size=3
    )
    
    await pool.initialize()
    
    try:
        # Concurrent operations using pool
        async def call_tool(tool_name: str, args: dict):
            async with pool.get_connection() as session:
                result = await session.call_tool(tool_name, args)
                return result
        
        # Execute multiple authenticated calls concurrently
        tasks = [
            call_tool("process_data", {"data": f"item_{i}"})
            for i in range(10)
        ]
        
        results = await asyncio.gather(*tasks)
        print(f"Processed {len(results)} requests")
        
    finally:
        await pool.close()

if __name__ == "__main__":
    asyncio.run(pooled_oauth_example())
```

## Testing OAuth clients

### Mock OAuth server

```python
"""
Mock OAuth server for testing OAuth clients.
"""

import pytest
import asyncio
from aiohttp import web
import json

class MockOAuthServer:
    """Mock OAuth server for testing."""
    
    def __init__(self, port: int = 9999):
        self.port = port
        self.app = web.Application()
        self.runner = None
        self.site = None
        
        # Setup routes
        self.app.router.add_post('/oauth/token', self._handle_token)
        self.app.router.add_get('/oauth/authorize', self._handle_authorize)
        self.app.router.add_post('/device/code', self._handle_device_code)
        
        # Test data
        self.valid_codes = set()
        self.valid_tokens = set()
    
    async def start(self):
        """Start the mock server."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, 'localhost', self.port)
        await self.site.start()
    
    async def stop(self):
        """Stop the mock server."""
        if self.runner:
            await self.runner.cleanup()
    
    async def _handle_token(self, request):
        """Handle token requests."""
        data = await request.post()
        grant_type = data.get('grant_type')
        
        if grant_type == 'authorization_code':
            code = data.get('code')
            if code not in self.valid_codes:
                return web.json_response(
                    {'error': 'invalid_grant'},
                    status=400
                )
            
            # Generate token
            token = f"access_token_{len(self.valid_tokens)}"
            self.valid_tokens.add(token)
            
            return web.json_response({
                'access_token': token,
                'token_type': 'Bearer',
                'expires_in': 3600,
                'refresh_token': f"refresh_token_{len(self.valid_tokens)}"
            })
        
        elif grant_type == 'client_credentials':
            client_id = data.get('client_id')
            client_secret = data.get('client_secret')
            
            if client_id == 'test_client' and client_secret == 'test_secret':
                token = f"service_token_{len(self.valid_tokens)}"
                self.valid_tokens.add(token)
                
                return web.json_response({
                    'access_token': token,
                    'token_type': 'Bearer',
                    'expires_in': 3600
                })
        
        return web.json_response({'error': 'unsupported_grant_type'}, status=400)
    
    async def _handle_authorize(self, request):
        """Handle authorization requests."""
        # Generate and store auth code
        auth_code = f"auth_code_{len(self.valid_codes)}"
        self.valid_codes.add(auth_code)
        
        # Redirect with code
        redirect_uri = request.query.get('redirect_uri')
        state = request.query.get('state', '')
        
        redirect_url = f"{redirect_uri}?code={auth_code}&state={state}"
        return web.Response(
            status=302,
            headers={'Location': redirect_url}
        )
    
    async def _handle_device_code(self, request):
        """Handle device code requests."""
        return web.json_response({
            'device_code': 'test_device_code',
            'user_code': 'TEST123',
            'verification_uri': f'http://localhost:{self.port}/device/verify',
            'verification_uri_complete': f'http://localhost:{self.port}/device/verify?code=TEST123',
            'expires_in': 1800,
            'interval': 1
        })

# Test fixtures
@pytest.fixture
async def mock_oauth_server():
    """Pytest fixture for mock OAuth server."""
    server = MockOAuthServer()
    await server.start()
    yield server
    await server.stop()

@pytest.mark.asyncio
async def test_oauth_client_credentials(mock_oauth_server):
    """Test client credentials flow."""
    config = OAuthConfig(
        client_id="test_client",
        client_secret="test_secret",
        token_url=f"http://localhost:{mock_oauth_server.port}/oauth/token",
        flow=OAuthFlow.CLIENT_CREDENTIALS
    )
    
    tokens = await client_credentials_flow(config)
    
    assert 'access_token' in tokens
    assert tokens['token_type'] == 'Bearer'
    assert 'expires_in' in tokens

@pytest.mark.asyncio
async def test_token_refresh():
    """Test automatic token refresh."""
    config = load_oauth_config()
    token_store = FileTokenStore(".test_tokens.json")
    
    # Create client with mock tokens
    client = AutoRefreshOAuthClient(config, token_store)
    
    # Test token validation and refresh logic
    expired_tokens = {
        'access_token': 'expired_token',
        'refresh_token': 'valid_refresh',
        'expires_at': time.time() - 3600  # Expired 1 hour ago
    }
    
    await token_store.save_tokens(expired_tokens)
    
    # This should trigger token refresh
    await client.authenticate()
    
    # Cleanup
    await token_store.clear_tokens()
```

## Best practices

### Security guidelines

- **Store secrets securely** - Use environment variables or secure vaults
- **Validate tokens** - Always validate token expiration and scope
- **Use PKCE** - Enable PKCE for public clients
- **Rotate tokens** - Implement proper token refresh
- **Secure storage** - Encrypt stored tokens when possible

### Performance optimization

- **Connection pooling** - Reuse authenticated connections
- **Token caching** - Cache valid tokens to avoid re-authentication
- **Async operations** - Use async/await for all OAuth operations
- **Batch requests** - Group multiple operations when possible
- **Monitor expiration** - Proactively refresh tokens before expiration

### Error handling

- **Retry logic** - Implement exponential backoff for token refresh
- **Graceful degradation** - Handle authentication failures gracefully
- **Logging** - Log authentication events for debugging
- **User feedback** - Provide clear error messages to users
- **Fallback strategies** - Have backup authentication methods

## Next steps

- **[Display utilities](display-utilities.md)** - UI helpers for OAuth flows
- **[Parsing results](parsing-results.md)** - Handle authenticated responses  
- **[Writing clients](writing-clients.md)** - General client development patterns
- **[Authentication](authentication.md)** - Server-side authentication implementation