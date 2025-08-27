# OAuth TokenHandler Enhancement - Issue #1315

## Overview

This enhancement addresses GitHub issue #1315, which requested that the `TokenHandler` should check the `Authorization` header for client credentials when they are missing from the request body.

## Problem

Previously, the `TokenHandler` only looked for client credentials (`client_id` and `client_secret`) in the request form data. However, according to OAuth 2.0 specifications, client credentials can also be provided in the `Authorization` header using Basic authentication. When credentials were only provided in the header, the handler would throw a `ValidationError` even though valid credentials were present.

## Solution

The `TokenHandler.handle()` method has been enhanced to:

1. **Primary**: Continue using client credentials from form data when available
2. **Fallback**: Check the `Authorization` header for Basic authentication when `client_id` is missing from form data
3. **Graceful degradation**: Handle malformed or invalid Authorization headers without breaking the existing flow

## Implementation Details

### Code Changes

The enhancement was implemented in `src/mcp/server/auth/handlers/token.py`:

```python
async def handle(self, request: Request):
    try:
        form_data = dict(await request.form())

        # Try to get client credentials from header if missing in body
        if "client_id" not in form_data:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Basic "):
                encoded = auth_header.split(" ")[1]
                decoded = base64.b64decode(encoded).decode("utf-8")
                client_id, _, client_secret = decoded.partition(":")
                client_secret = urllib.parse.unquote(client_secret)
                form_data.setdefault("client_id", client_id)
                form_data.setdefault("client_secret", client_secret)

        token_request = TokenRequest.model_validate(form_data).root
        # ... rest of the method
```

### Key Features

- **Base64 Decoding**: Properly decodes Basic authentication credentials
- **URL Decoding**: Handles URL-encoded client secrets (e.g., `test%2Bsecret` → `test+secret`)
- **Non-intrusive**: Only activates when credentials are missing from form data
- **Backward Compatible**: Existing functionality remains unchanged

## Testing

Comprehensive tests have been added in `tests/server/auth/test_token_handler.py` covering:

1. **Form Data Credentials**: Existing functionality continues to work
2. **Authorization Header Fallback**: New functionality works correctly
3. **URL-encoded Secrets**: Handles special characters in client secrets
4. **Invalid Headers**: Gracefully handles malformed Authorization headers
5. **Refresh Token Grants**: Works with both grant types
6. **Error Cases**: Proper validation when no credentials are provided

### Test Coverage

- ✅ `test_handle_with_form_data_credentials`
- ✅ `test_handle_with_authorization_header_credentials`
- ✅ `test_handle_with_authorization_header_url_encoded_secret`
- ✅ `test_handle_with_invalid_authorization_header`
- ✅ `test_handle_with_malformed_basic_auth`
- ✅ `test_handle_with_refresh_token_grant`
- ✅ `test_handle_without_credentials_fails`

## OAuth 2.0 Compliance

This enhancement improves compliance with OAuth 2.0 specifications by supporting both authentication methods:

- **client_secret_post** (form data) - RFC 6749 Section 2.3.1
- **client_secret_basic** (Authorization header) - RFC 6749 Section 2.3.1

## Impact

- **Positive**: Improves OAuth 2.0 compliance and client compatibility
- **Neutral**: No breaking changes to existing functionality
- **Performance**: Minimal overhead (only processes header when needed)

## Files Modified

1. **`src/mcp/server/auth/handlers/token.py`** - Main implementation
2. **`tests/server/auth/test_token_handler.py`** - New test suite

## Verification

- ✅ All new tests pass
- ✅ All existing tests continue to pass
- ✅ Code passes linting (ruff)
- ✅ Code passes type checking (pyright)
- ✅ No breaking changes to existing functionality

## Usage Example

Clients can now use either method:

**Method 1: Form Data (existing)**
```http
POST /token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code&code=abc123&client_id=myapp&client_secret=secret
```

**Method 2: Authorization Header (new)**
```http
POST /token
Authorization: Basic bXlhcHA6c2VjcmV0
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code&code=abc123
```

Both methods will work seamlessly with the enhanced `TokenHandler`.
