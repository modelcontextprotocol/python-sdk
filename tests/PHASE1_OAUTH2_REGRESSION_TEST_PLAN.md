# Phase 1 OAuth2 Regression Test Plan

Verify that Phase 1 (multi-protocol auth infrastructure) does **not** break existing MCP OAuth2 authentication. The existing flow uses only RFC 9728 / Bearer and does not pass the new optional parameters; all new code must remain backward compatible.

---

## 1. Objectives

| Objective | Description |
|-----------|-------------|
| **Backward compatibility** | Existing OAuth2 client and server behavior unchanged when new optional params are not used. |
| **Discovery** | Client still discovers PRM and AS metadata; server still returns RFC 9728 PRM and correct WWW-Authenticate. |
| **End-to-end** | Full flow with `simple-auth` (AS + RS) and `simple-auth-client` completes: 401 → discovery → OAuth → token → MCP session → list tools → call tool. |

---

## 2. Scope of Phase 1 Code Under Test

| Area | Change | Backward compatibility |
|------|--------|-------------------------|
| **shared/auth.py** | `AuthProtocolMetadata`, `AuthCredentials`/`OAuthCredentials`/`APIKeyCredentials`, `ProtectedResourceMetadata` extended with `mcp_*` fields and `@model_validator` | PRM built from `authorization_servers` only still works; validator fills `mcp_auth_protocols` when absent. |
| **client/auth/protocol.py** | New file; `AuthProtocol`, `AuthContext`, etc. | Not used by existing OAuth path; no impact. |
| **client/auth/utils.py** | `extract_field_from_www_auth(..., auth_scheme=None)`, new extractors for `auth_protocols` / `default_protocol` / `protocol_preferences` | When `auth_scheme` is not passed, behavior unchanged (search full header). New extractors unused by current client. |
| **server/auth/middleware/bearer_auth.py** | `RequireAuthMiddleware` accepts optional `auth_protocols`, `default_protocol`, `protocol_preferences`; `_determine_auth_scheme`; WWW-Authenticate may include new params | When new params are not passed (current FastMCP/routes), middleware behaves as before: Bearer scheme, no new header params. |

---

## 3. Unit / Regression Tests

Run existing tests to ensure no regressions. Phase 1 does not change call sites: FastMCP still calls `RequireAuthMiddleware(app, required_scopes, resource_metadata_url)` without the new optional args; client still uses `extract_field_from_www_auth(response, "resource_metadata")` etc. without `auth_scheme`.

### 3.1 Data model

- **ProtectedResourceMetadata**
  - Construct with only `resource` and `authorization_servers` (no `mcp_*`).
  - After validation, `mcp_auth_protocols` is populated from `authorization_servers` and `mcp_default_auth_protocol == "oauth2"`.
  - Existing tests in `tests/client/test_auth.py` (e.g. `TestProtectedResourceMetadata`) and any that build `ProtectedResourceMetadata` must still pass.

### 3.2 Client utils

- **extract_field_from_www_auth**
  - Call with `auth_scheme=None` (default): existing behavior (search full header).
  - Tests in `test_extract_field_from_www_auth_valid_cases` and `test_extract_field_from_www_auth_invalid_cases` must pass unchanged.
- **extract_resource_metadata_from_www_auth**, **extract_scope_from_www_auth**: unchanged signatures; existing tests remain valid.

### 3.3 Server middleware

- **RequireAuthMiddleware**
  - Instantiate with only `(app, required_scopes, resource_metadata_url)`.
  - WWW-Authenticate must still start with `Bearer` and include `error`, `error_description`, and optionally `resource_metadata`; no requirement for `auth_protocols` / `default_protocol` / `protocol_preferences`.
- Existing tests in `tests/server/auth/middleware/test_bearer_auth.py` (e.g. `TestRequireAuthMiddleware`) must pass.

### 3.4 Commands

```bash
# From repo root
uv run pytest tests/client/test_auth.py tests/server/auth/middleware/test_bearer_auth.py -v
```

---

## 4. Integration Test: simple-auth + simple-auth-client

Manual (or script-assisted) run to confirm the full OAuth2 flow still works with Phase 1 code.

### 4.1 Prerequisites

- Repo root: `uv sync` (so `mcp-simple-auth`, `mcp-simple-auth-client`, and SDK are available).
- Ports 9000 (AS), 8001 (RS), 3030 (client callback) free.

### 4.2 Steps

1. **Start Authorization Server (AS)**  
   From `examples/servers/simple-auth`:

   ```bash
   uv run mcp-simple-auth-as --port=9000
   ```

2. **Start Resource Server (RS)**  
   In another terminal, from `examples/servers/simple-auth`:

   ```bash
   uv run mcp-simple-auth-rs --port=8001 --auth-server=http://localhost:9000 --transport=streamable-http
   ```

3. **Optional: Verify discovery (Phase 1 backward compat)**  
   - PRM (RFC 9728): `curl -s http://localhost:8001/.well-known/oauth-protected-resource`  
     - Must return JSON with `resource` and `authorization_servers` (and may include Phase 1 `mcp_*` if implementation fills them).
   - AS metadata: `curl -s http://localhost:9000/.well-known/oauth-authorization-server`  
     - Must return JSON with `issuer`, `authorization_endpoint`, `token_endpoint`.

4. **Run client**  
   From `examples/clients/simple-auth-client`:

   ```bash
   MCP_SERVER_PORT=8001 MCP_TRANSPORT_TYPE=streamable-http uv run mcp-simple-auth-client
   ```

5. **Complete OAuth in browser**  
   When the client prints the authorization URL, open it in a browser, complete the simple-auth login; redirect to `http://localhost:3030/callback`.

6. **Verify MCP session**  
   At `mcp>` prompt:
   - `list` → should list tools (e.g. `get_time`).
   - `call get_time {}` → should return current time.
   - `quit` → exit.

### 4.3 Success criteria

- No errors during discovery (client gets PRM and AS metadata).
- OAuth flow completes (authorization code → token).
- Client connects and initializes MCP session.
- `list` and `call get_time` succeed.
- WWW-Authenticate on 401 (if inspected) remains Bearer-based and usable by the existing client.

---

## 5. Automated Script (Optional)

Use the script `scripts/run_phase1_oauth2_integration_test.sh` to start AS and RS, wait for readiness, then run the client. You still complete OAuth in the browser and run `list` / `call get_time` / `quit` manually.

---

## 6. Checklist Summary

- [ ] `uv run pytest tests/client/test_auth.py tests/server/auth/middleware/test_bearer_auth.py -v` passes.
- [ ] AS and RS start without errors.
- [ ] PRM and AS discovery URLs return valid JSON.
- [ ] simple-auth-client completes OAuth and connects.
- [ ] `list` shows tools; `call get_time {}` returns time.
- [ ] No Phase 1 code paths required for this flow (optional params unused).
