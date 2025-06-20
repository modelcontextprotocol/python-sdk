# RFC 8707 Resource Indicators Implementation Plan

## Overview

This plan implements RFC 8707 Resource Indicators for OAuth 2.0 in the Python MCP SDK to prevent token confusion attacks. The implementation ensures tokens are explicitly bound to their intended MCP servers.

## Key Requirements

1. Clients **MUST** include `resource` parameter in authorization and token requests
2. MCP servers (Resource Servers) **MUST** validate tokens were issued for them
3. Authorization Servers **SHOULD** include resource in issued tokens (e.g., JWT `aud` claim)
4. Support hierarchical resource matching per PR #664

## Implementation Plan

### Phase 1: Shared Utilities

**New File: `src/mcp/shared/auth_utils.py`**

```python
def resource_url_from_server_url(url: str | HttpUrl) -> str:
    """Convert server URL to canonical resource URL per RFC 8707.
    - Removes fragment component
    - Returns absolute URI with lowercase scheme/host
    """

def check_resource_allowed(
    requested_resource: str, 
    configured_resource: str
) -> bool:
    """Check if requested resource matches configured resource.
    Supports hierarchical matching where a token for a parent 
    resource can be used for child resources.
    """
```

**New File: `tests/shared/test_auth_utils.py`**
- Test canonical URL generation
- Test hierarchical resource matching
- Test edge cases (trailing slashes, ports, paths)

### Phase 2: Client-Side Implementation

**File: `src/mcp/client/auth.py`**

1. **Add resource parameter to OAuth flows:**
   ```python
   async def _start_authorization(self, state: str | None = None) -> str:
       # Add resource to authorization URL
       params = {
           "client_id": self._client_info.client_id,
           "redirect_uri": str(self._redirect_uri),
           "response_type": "code",
           "code_challenge": code_challenge,
           "code_challenge_method": "S256",
           "resource": self._resource_url,  # NEW
           ...
       }
   ```

2. **Add resource to token exchange:**
   ```python
   async def _exchange_authorization_code(self, code: str) -> OAuthToken:
       data = {
           "grant_type": "authorization_code",
           "code": code,
           "redirect_uri": str(self._redirect_uri),
           "code_verifier": self._context.code_verifier,
           "resource": self._resource_url,  # NEW
           ...
       }
   ```

3. **Add resource to token refresh:**
   ```python
   async def _refresh_access_token(self) -> OAuthToken:
       data = {
           "grant_type": "refresh_token",
           "refresh_token": self._context.refresh_token,
           "resource": self._resource_url,  # NEW
           ...
       }
   ```

4. **Add resource selection logic:**
   ```python
   async def _select_resource_url(self) -> str:
       """Select resource URL based on server URL and PRM."""
       resource = resource_url_from_server_url(str(self._server_url))
       
       if self._prm_metadata and self._prm_metadata.resource:
           # Use PRM resource if it's a valid parent
           if check_resource_allowed(
               requested_resource=resource,
               configured_resource=self._prm_metadata.resource
           ):
               resource = self._prm_metadata.resource
       
       return resource
   ```

### Phase 3: Server-Side Authorization Server

**File: `src/mcp/server/auth/handlers/authorize.py`**

1. **Update request model:**
   ```python
   class AuthorizationRequest(BaseModel):
       client_id: str
       redirect_uri: HttpUrl
       response_type: str
       scope: Optional[str] = None
       state: Optional[str] = None
       code_challenge: Optional[str] = None
       code_challenge_method: Optional[str] = None
       resource: Optional[str] = None  # NEW
   ```

2. **Pass resource to provider:**
   ```python
   authorization_params = AuthorizationParams(
       client_id=request.client_id,
       redirect_uri=str(request.redirect_uri),
       scope=request.scope,
       state=request.state,
       code_challenge=request.code_challenge,
       code_challenge_method=request.code_challenge_method,
       resource=request.resource,  # NEW
   )
   ```

**File: `src/mcp/server/auth/handlers/token.py`**

1. **Update request models:**
   ```python
   class AuthorizationCodeRequest(BaseModel):
       grant_type: Literal["authorization_code"]
       code: str
       redirect_uri: str
       code_verifier: Optional[str] = None
       client_id: Optional[str] = None
       client_secret: Optional[str] = None
       resource: Optional[str] = None  # NEW

   class RefreshTokenRequest(BaseModel):
       grant_type: Literal["refresh_token"]
       refresh_token: str
       scope: Optional[str] = None
       client_id: Optional[str] = None
       client_secret: Optional[str] = None
       resource: Optional[str] = None  # NEW
   ```

2. **Pass resource to provider methods:**
   ```python
   # In authorization code exchange
   token = await provider.exchange_authorization_code(
       client=authenticated_client,
       code=request.code,
       code_verifier=request.code_verifier,
       resource=request.resource,  # NEW
   )
   
   # In refresh token exchange
   token = await provider.exchange_refresh_token(
       client=authenticated_client,
       refresh_token=request.refresh_token,
       scope=request.scope,
       resource=request.resource,  # NEW
   )
   ```

**File: `src/mcp/server/auth/provider.py`**

1. **Update data models:**
   ```python
   @dataclass
   class AuthorizationParams:
       client_id: str
       redirect_uri: str
       scope: Optional[str] = None
       state: Optional[str] = None
       code_challenge: Optional[str] = None
       code_challenge_method: Optional[str] = None
       resource: Optional[str] = None  # NEW

   @dataclass
   class AuthorizationCode:
       code: str
       client_id: str
       redirect_uri: str
       code_challenge: Optional[str] = None
       expires_at: datetime
       resource: Optional[str] = None  # NEW

   @dataclass
   class AccessToken:
       token: str
       client_id: str
       scope: Optional[str] = None
       expires_at: Optional[datetime] = None
       resource: Optional[str] = None  # NEW
   ```

2. **Update provider protocol:**
   ```python
   class OAuthAuthorizationServerProvider(Protocol):
       async def exchange_authorization_code(
           self,
           client: OAuthClientInformationFull,
           code: str,
           code_verifier: Optional[str] = None,
           resource: Optional[str] = None,  # NEW
       ) -> OAuthToken:
           """Exchange authorization code for tokens.
           Should include resource in token (e.g., JWT aud claim)."""
           ...

       async def exchange_refresh_token(
           self,
           client: OAuthClientInformationFull,
           refresh_token: str,
           scope: Optional[str] = None,
           resource: Optional[str] = None,  # NEW
       ) -> OAuthToken:
           """Refresh access token.
           Should maintain resource from original token."""
           ...
   ```

### Phase 4: Resource Server Token Validation

**File: `examples/servers/simple-auth/mcp_simple_auth/token_verifier.py`**

Extend the existing token verifier to support RFC 8707 resource validation:

```python
# Add to existing IntrospectionTokenVerifier class
class IntrospectionTokenVerifier:
    def __init__(
        self, 
        introspection_endpoint: str,
        server_url: str | None = None,  # NEW
        strict_resource_validation: bool = False  # NEW
    ):
        self.introspection_endpoint = introspection_endpoint
        self.server_url = server_url
        self.strict_validation = strict_resource_validation
        if server_url:
            from mcp.shared.auth_utils import resource_url_from_server_url
            self.resource_url = resource_url_from_server_url(server_url)
    
    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify token via introspection endpoint."""
        # ... existing introspection code ...
        
        # After getting introspection response:
        if self.server_url and not self._validate_resource(data):
            logger.warning(
                f"Token resource validation failed. "
                f"Expected: {self.resource_url}"
            )
            return None
        
        return AccessToken(
            token=token,
            client_id=data.get("client_id", "unknown"),
            scopes=data.get("scope", "").split() if data.get("scope") else [],
            expires_at=data.get("exp"),
            resource=data.get("aud") or data.get("resource"),  # NEW
        )
    
    def _validate_resource(self, token_data: dict) -> bool:
        """Validate token was issued for this resource server."""
        if not self.server_url:
            return True  # No validation if server URL not configured
        
        from mcp.shared.auth_utils import check_resource_allowed
        
        # Check 'aud' claim first (standard JWT audience)
        aud = token_data.get("aud")
        if isinstance(aud, list):
            for audience in aud:
                if self._is_valid_resource(audience):
                    return True
            return False
        elif aud:
            return self._is_valid_resource(aud)
        
        # Check custom 'resource' claim if no 'aud'
        resource = token_data.get("resource")
        if resource:
            return self._is_valid_resource(resource)
        
        # No resource binding - invalid per RFC 8707
        return False
    
    def _is_valid_resource(self, resource: str) -> bool:
        """Check if resource matches this server."""
        if self.strict_validation:
            return resource == self.resource_url
        else:
            return check_resource_allowed(
                requested_resource=self.resource_url,
                configured_resource=resource
            )
```

### Phase 5: Example Updates

**File: `examples/servers/simple-auth/mcp_simple_auth/github_oauth_provider.py`** (Authorization Server)

Update the AS provider to:
1. Accept resource parameter in authorization and token requests
2. Store resource with issued tokens
3. Include resource in token responses (e.g., as JWT `aud` claim)

```python
# In authorize method
async def authorize(self, params: AuthorizationParams) -> str:
    # Store resource with authorization code
    self._pending_authorizations[code] = {
        "client_id": params.client_id,
        "redirect_uri": params.redirect_uri,
        "code_challenge": params.code_challenge,
        "resource": params.resource,  # NEW - store for token issuance
        ...
    }

# In exchange_authorization_code method
async def exchange_authorization_code(
    self,
    client: OAuthClientInformationFull,
    code: str,
    code_verifier: Optional[str] = None,
    resource: Optional[str] = None,  # NEW
) -> OAuthToken:
    # Include resource in token (implementation-specific)
    # Could be JWT with aud claim, or stored server-side
    # The AS is responsible for including this in the token
    # so the RS can validate it later
    ...
```

**File: `examples/servers/simple-auth/server.py`** (Resource Server - MCP Server)

Update the MCP server example to validate tokens:
1. Add token validation before processing requests
2. Add optional strict validation mode (like TypeScript's `--oauth-strict`)
3. Demonstrate resource validation using the updated IntrospectionTokenVerifier

```python
from mcp_simple_auth.token_verifier import IntrospectionTokenVerifier

# In the MCP server setup
async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--oauth-strict", action="store_true", 
                       help="Enable strict resource validation")
    args = parser.parse_args()
    
    server_url = "https://mcp.example.com/server"
    
    # Initialize token verifier with resource validation
    token_verifier = IntrospectionTokenVerifier(
        introspection_endpoint="https://auth.example.com/introspect",
        server_url=server_url,  # Enable resource validation
        strict_resource_validation=args.oauth_strict
    )
    
    # Use the verifier in server middleware
    async def validate_request(auth_header: str) -> bool:
        """Validate incoming request has valid token for this server."""
        token = extract_bearer_token(auth_header)
        access_token = await token_verifier.verify_token(token)
        
        if not access_token:
            raise InvalidTokenError(
                f"Token validation failed. "
                f"Expected resource: {token_verifier.resource_url}"
            )
        
        return True
```

### Phase 6: Testing

**Updated Tests:**

1. `tests/client/test_auth.py`:
   - Assert resource parameter in authorization URL
   - Assert resource parameter in token requests
   - Test resource selection logic with PRM

2. `tests/server/auth/handlers/test_authorize.py`:
   - Test resource parameter acceptance
   - Test resource passed to provider

3. `tests/server/auth/handlers/test_token.py`:
   - Test resource in code exchange
   - Test resource in refresh requests

**New Tests:**

1. `tests/server/auth/test_token_validator.py`:
   - Test strict vs hierarchical validation
   - Test multiple audience handling
   - Test missing resource rejection

### Phase 7: Documentation

**Update `README.md`:**
- Add a section on RFC 8707 Resource Indicators
- Explain the security benefits
- Show example usage with `--oauth-strict` flag
- Provide migration guidance for existing implementations

## Migration Strategy

1. **Backward Compatibility:**
   - All resource parameters are optional
   - Existing code continues to work
   - Gradual adoption possible

2. **Rollout Phases:**
   - Phase 1: Clients start sending resource parameter
   - Phase 2: AS providers start including in tokens
   - Phase 3: RS servers start validating (warn only)
   - Phase 4: RS servers enforce validation


## Security Considerations

1. **Token Binding:**
   - Always include resource in tokens (JWT `aud` claim preferred)
   - Validate on every authenticated request
   - Consider token introspection for opaque tokens

2. **Hierarchical Matching:**
   - Default: Allow parent resource tokens
   - Strict mode: Exact match only
   - Document security implications

3. **Multiple Resources:**
   - Not supported in initial implementation
   - Can be added later if needed

## Success Criteria

1. ✅ Clients automatically include resource parameter
2. ✅ AS providers can include resource in tokens
3. ✅ RS servers can validate token resources
4. ✅ Hierarchical matching works correctly
5. ✅ Examples demonstrate proper usage
6. ✅ No breaking changes for existing code
7. ✅ Comprehensive test coverage
8. ✅ Clear migration documentation