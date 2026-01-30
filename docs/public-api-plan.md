# Public API Hardening Plan for v2

## Problem Statement

In v1, nearly every module, class, function, and type was importable by end users—even internal implementation details. This meant routine refactors (renaming a helper, reordering a base class, changing an internal constant) could break downstream code. The root cause: there was no enforced distinction between "public" and "private."

Audit of the current surface reveals:

- **~40 implementation modules** have no `_` prefix and are directly importable, but are never surfaced through any `__init__.py`—they are accidental public API
- **Zero implementation modules** (except `_httpx_utils.py`) declare `__all__`, so star imports from them leak every top-level name
- **Name collisions** exist (two independent `RequestContext` classes in `shared.context` and `client.streamable_http`)
- **`shared/` has an empty `__init__.py`**—every internal utility is importable via `from mcp.shared.session import BaseSession`
- **`server/auth/` subtree has zero re-exports**—all auth internals are reachable by deep module path but never declared public
- **The `mcp/__init__.py` imports `ServerSession` directly from `server/session.py`**, bypassing `server/__init__.py`

## Design Principles

1. **Private by default.** Every symbol starts as private. Public status must be explicitly granted via `__all__` in the package `__init__.py`.
2. **Module filenames enforce privacy.** Implementation files are named `_module.py`. Only `__init__.py` files are the public face of each package.
3. **Stable import paths.** Users import from package roots (`mcp`, `mcp.types`, `mcp.server`, `mcp.client`), never from leaf implementation files.
4. **Protocol types are inherently public.** The `mcp.types` module mirrors the MCP spec schema—every type in the spec is public.
5. **Experimental is opt-in and explicitly unstable.** Anything under `.experimental` namespaces carries no stability guarantee.
6. **Enforcement is automated.** A CI-checked allowlist script prevents accidental surface growth.

## Methodology

The enumeration uses a "private-by-default, explicitly public" approach:

1. **Enumerate** every importable symbol in the package (automated — see Tooling)
2. **Classify** each symbol: Public / Private / Experimental / Needs-Decision
3. **Public symbols**: surface through the correct `__init__.py` + `__all__`, reachable from a stable path
4. **Private symbols**: rename the containing module to `_module.py`, or prefix the name with `_`
5. **Needs-Decision**: explicit team call before shipping
6. **Enforce**: CI audit script compares the live importable surface against the checked-in allowlist on every PR

---

## Recommended Tooling

### 1. Custom CI audit script (`scripts/audit_public_api.py`) — **most important**

This is the enforcement mechanism that makes the public API a reviewable artifact. It does:

- Walks all modules in `src/mcp/`
- Flags any non-`__init__.py` module without a `_` prefix as a "leaked module"
- Flags any `__init__.py` missing `__all__`
- Collects the full public surface (union of all `__all__` declarations)
- Compares against a checked-in allowlist (`docs/public_api_allowlist.txt`)
- Fails if any new name appears that isn't allowlisted, or if an allowlisted name disappears

This runs in CI on every PR. Adding to the public API becomes an explicit, reviewable choice.

### 2. `griffe` — already available via `mkdocstrings`

`griffe` extracts the full public API from source without executing code, respecting `__all__` and `_` conventions. Since it's already a dependency for the docs build, it can power the audit script or standalone analysis:

```python
from griffe import load

package = load("mcp")
# package.members gives the full public surface tree
```

This also means the mkdocs API reference docs automatically reflect only the declared public surface once we tighten the modules.

### 3. `pyright` `reportPrivateUsage` — already enabled in strict mode

Once modules are renamed to `_module.py`, pyright will flag any import from them outside the `mcp` package. This gives free enforcement for test code and downstream users without additional configuration.

### 4. `ruff` rules already in place

- `F822` catches undefined names in `__all__`
- `F401` catches unused imports (drift between import and `__all__`)
- These already run in pre-commit; they'll catch `__init__.py` drift automatically

### 5. Type stubs (`.pyi`) — Phase 3, long-term

Generate `.pyi` stubs for the public surface and check them in. API changes become visible as stub file diffs in PRs. Tooling: `stubgen` (mypy) or griffe can generate them.

---

## The Public API Allowlist

Everything below is explicitly public. Everything not listed becomes private.

### Tier 1: Core Entry Points

Import from `mcp` or `mcp.client` / `mcp.server`.

| Symbol | Stable import path | Notes |
|---|---|---|
| `Client` | `mcp.Client` | Main client entry point (wraps in-memory server) |
| `ClientSession` | `mcp.ClientSession` | Full-featured session over any transport |
| `ClientSessionGroup` | `mcp.ClientSessionGroup` | Multi-server aggregation |
| `MCPServer` | `mcp.server.MCPServer` | High-level decorator-based server |
| `Server` | `mcp.server.Server` | Low-level handler-registration server |
| `ServerSession` | `mcp.ServerSession` | Server-side session |
| `Context` | `mcp.server.mcpserver.Context` | Request context passed to MCPServer handlers |
| `MCPError` | `mcp.MCPError` | Base exception for MCP protocol errors |
| `UrlElicitationRequiredError` | `mcp.UrlElicitationRequiredError` | Thrown when URL elicitation is required |

### Tier 2: Transports & Connection Parameters

Transport entry-point functions and their configuration types. Currently these leak via direct module import; they should be surfaced through `__init__.py`.

| Symbol | Proposed stable path | Current location |
|---|---|---|
| `stdio_client` | `mcp.stdio_client` | `mcp.client.stdio` ✓ already re-exported |
| `stdio_server` | `mcp.stdio_server` | `mcp.server.stdio` ✓ already re-exported |
| `sse_client` | `mcp.client.sse_client` | `mcp.client.sse` — **not re-exported** |
| `streamable_http_client` | `mcp.client.streamable_http_client` | `mcp.client.streamable_http` — **not re-exported** |
| `websocket_client` | `mcp.client.websocket_client` | `mcp.client.websocket` — **not re-exported** |
| `StdioServerParameters` | `mcp.StdioServerParameters` | ✓ already re-exported |
| `SseServerParameters` | `mcp.client.SseServerParameters` | `mcp.client.session_group` — **not re-exported** |
| `StreamableHttpParameters` | `mcp.client.StreamableHttpParameters` | `mcp.client.session_group` — **not re-exported** |
| `ServerParameters` | `mcp.client.ServerParameters` | `mcp.client.session_group` — **not re-exported** |
| `ClientSessionParameters` | `mcp.client.ClientSessionParameters` | `mcp.client.session_group` — **not re-exported** |
| `SseServerTransport` | `mcp.server.SseServerTransport` | `mcp.server.sse` — **not re-exported** |
| `EventStore` | `mcp.server.EventStore` | `mcp.server.streamable_http` — **not re-exported** |
| `TransportSecuritySettings` | `mcp.server.TransportSecuritySettings` | `mcp.server.transport_security` — **not re-exported** |

### Tier 3: MCPServer Resource / Tool / Prompt Types

User-facing wrapper types for defining server capabilities.

| Symbol | Stable import path |
|---|---|
| `Tool` | `mcp.server.mcpserver.tools.Tool` |
| `Resource` | `mcp.server.mcpserver.resources.Resource` |
| `TextResource` | `mcp.server.mcpserver.resources.TextResource` |
| `BinaryResource` | `mcp.server.mcpserver.resources.BinaryResource` |
| `FunctionResource` | `mcp.server.mcpserver.resources.FunctionResource` |
| `FileResource` | `mcp.server.mcpserver.resources.FileResource` |
| `HttpResource` | `mcp.server.mcpserver.resources.HttpResource` |
| `DirectoryResource` | `mcp.server.mcpserver.resources.DirectoryResource` |
| `ResourceTemplate` | `mcp.server.mcpserver.resources.ResourceTemplate` |
| `Prompt` | `mcp.server.mcpserver.prompts.Prompt` |
| `Image` | `mcp.server.mcpserver.Image` |
| `Audio` | `mcp.server.mcpserver.Audio` |
| `NotificationOptions` | `mcp.server.NotificationOptions` |
| `InitializationOptions` | `mcp.server.InitializationOptions` |

### Tier 4: Auth

Client and server auth types. Currently all server auth types are importable only via deep paths with zero `__init__.py` re-export.

| Symbol | Proposed stable path | Current location |
|---|---|---|
| `OAuthClientProvider` | `mcp.client.auth.OAuthClientProvider` | ✓ already re-exported |
| `TokenStorage` | `mcp.client.auth.TokenStorage` | ✓ already re-exported |
| `PKCEParameters` | `mcp.client.auth.PKCEParameters` | ✓ already re-exported |
| `OAuthFlowError` | `mcp.client.auth.OAuthFlowError` | ✓ already re-exported |
| `OAuthRegistrationError` | `mcp.client.auth.OAuthRegistrationError` | ✓ already re-exported |
| `OAuthTokenError` | `mcp.client.auth.OAuthTokenError` | ✓ already re-exported |
| `OAuthAuthorizationServerProvider` | `mcp.server.auth.OAuthAuthorizationServerProvider` | `mcp.server.auth.provider` — **not re-exported** |
| `TokenVerifier` | `mcp.server.auth.TokenVerifier` | `mcp.server.auth.provider` — **not re-exported** |
| `AuthSettings` | `mcp.server.auth.AuthSettings` | `mcp.server.auth.settings` — **not re-exported** |

### Tier 5: Elicitation Result Types

Returned from `Context.elicit()` and `Context.elicit_url()` in MCPServer handlers.

| Symbol | Proposed stable path | Current location |
|---|---|---|
| `ElicitationResult` | `mcp.server.ElicitationResult` | `mcp.server.elicitation` — **not re-exported** |
| `UrlElicitationResult` | `mcp.server.UrlElicitationResult` | `mcp.server.elicitation` — **not re-exported** |
| `AcceptedElicitation` | `mcp.server.AcceptedElicitation` | `mcp.server.elicitation` — **not re-exported** |
| `DeclinedElicitation` | `mcp.server.DeclinedElicitation` | `mcp.server.elicitation` — **not re-exported** |
| `CancelledElicitation` | `mcp.server.CancelledElicitation` | `mcp.server.elicitation` — **not re-exported** |

### Tier 6: Callback Protocol Types

Users need these for type annotations when passing callbacks to `Client` or `ClientSession`. Currently defined in `client/session.py` with no re-export.

| Symbol | Proposed stable path |
|---|---|
| `SamplingFnT` | `mcp.client.SamplingFnT` |
| `ElicitationFnT` | `mcp.client.ElicitationFnT` |
| `ListRootsFnT` | `mcp.client.ListRootsFnT` |
| `LoggingFnT` | `mcp.client.LoggingFnT` |
| `MessageHandlerFnT` | `mcp.client.MessageHandlerFnT` |

### Tier 7: Protocol Types (`mcp.types`)

**All ~200 types currently in `mcp.types.__all__` remain public.** These mirror the MCP spec and are inherently part of the public contract. The internal `mcp.types._types` is already correctly private. The `mcp.types.jsonrpc` module should be renamed to `_jsonrpc.py` (everything is already re-exported through `types/__init__.py`).

### Tier 8: Experimental (Explicitly Unstable)

Everything under `*.experimental.*` namespaces. Importable, but documented as "may change without notice" and not covered by semver stability.

---

## What Gets Privatized

### Implementation Modules to Rename

Rename from `module.py` to `_module.py`. All public symbols are preserved via re-exports in the package `__init__.py`.

**`src/mcp/client/`**

| Current | Renamed | Re-export destination |
|---|---|---|
| `client.py` | `_client.py` | `client/__init__.py` |
| `session.py` | `_session.py` | `client/__init__.py` |
| `session_group.py` | `_session_group.py` | `client/__init__.py` |
| `sse.py` | `_sse.py` | `client/__init__.py` |
| `stdio.py` | `_stdio.py` | `client/__init__.py` + `mcp/__init__.py` |
| `streamable_http.py` | `_streamable_http.py` | `client/__init__.py` |
| `websocket.py` | `_websocket.py` | `client/__init__.py` |

**`src/mcp/client/auth/`**

| Current | Renamed |
|---|---|
| `exceptions.py` | `_exceptions.py` |
| `oauth2.py` | `_oauth2.py` |
| `utils.py` | `_utils.py` |
| `extensions/client_credentials.py` | `extensions/_client_credentials.py` |

**`src/mcp/server/`**

| Current | Renamed | Re-export destination |
|---|---|---|
| `session.py` | `_session.py` | `mcp/__init__.py` |
| `sse.py` | `_sse.py` | `server/__init__.py` |
| `stdio.py` | `_stdio.py` | `mcp/__init__.py` |
| `streamable_http.py` | `_streamable_http.py` | `server/__init__.py` |
| `streamable_http_manager.py` | `_streamable_http_manager.py` | — (internal only) |
| `transport_security.py` | `_transport_security.py` | `server/__init__.py` |
| `validation.py` | `_validation.py` | — (internal only) |
| `elicitation.py` | `_elicitation.py` | `server/__init__.py` |
| `models.py` | `_models.py` | `server/__init__.py` |
| `websocket.py` | `_websocket.py` | — (internal only, server side) |

**`src/mcp/server/lowlevel/`**

| Current | Renamed |
|---|---|
| `server.py` | `_server.py` |
| `func_inspection.py` | `_func_inspection.py` |
| `helper_types.py` | `_helper_types.py` |
| `experimental.py` | `_experimental.py` |

**`src/mcp/server/mcpserver/`**

| Current | Renamed |
|---|---|
| `server.py` | `_server.py` |
| `exceptions.py` | `_exceptions.py` |
| `prompts/base.py` | `prompts/_base.py` |
| `prompts/manager.py` | `prompts/_manager.py` |
| `resources/base.py` | `resources/_base.py` |
| `resources/resource_manager.py` | `resources/_resource_manager.py` |
| `resources/templates.py` | `resources/_templates.py` |
| `resources/types.py` | `resources/_types.py` |
| `tools/base.py` | `tools/_base.py` |
| `tools/tool_manager.py` | `tools/_tool_manager.py` |
| `utilities/context_injection.py` | `utilities/_context_injection.py` |
| `utilities/func_metadata.py` | `utilities/_func_metadata.py` |
| `utilities/logging.py` | `utilities/_logging.py` |
| `utilities/types.py` | `utilities/_types.py` |

**`src/mcp/server/auth/` (entire subtree)**

All handler, middleware, route, and settings files → prefix with `_`. Re-export public types through `auth/__init__.py`.

**`src/mcp/shared/` (entire package is internal)**

| Current | Renamed |
|---|---|
| `auth.py` | `_auth.py` |
| `auth_utils.py` | `_auth_utils.py` |
| `context.py` | `_context.py` |
| `exceptions.py` | `_exceptions.py` |
| `memory.py` | `_memory.py` |
| `message.py` | `_message.py` |
| `metadata_utils.py` | `_metadata_utils.py` |
| `progress.py` | `_progress.py` |
| `response_router.py` | `_response_router.py` |
| `session.py` | `_session.py` |
| `tool_name_validation.py` | `_tool_name_validation.py` |
| `version.py` | `_version.py` |

**`src/mcp/types/`**

| Current | Renamed |
|---|---|
| `jsonrpc.py` | `_jsonrpc.py` |

**`src/mcp/cli/`**

| Current | Renamed |
|---|---|
| `cli.py` | `_cli.py` |
| `claude.py` | `_claude.py` |

**`src/mcp/os/`**

| Current | Renamed |
|---|---|
| `posix/utilities.py` | `posix/_utilities.py` |
| `win32/utilities.py` | `win32/_utilities.py` |

### Internal Names to Prefix with `_`

These are names inside modules that should not be part of any public surface:

| Name | Module | Reason |
|---|---|---|
| `DEFAULT_CLIENT_INFO` | `client/session.py` | Implementation detail |
| `ClientResponse` (TypeAdapter) | `client/session.py` | Internal deserialization |
| `PROCESS_TERMINATION_TIMEOUT` | `client/stdio.py` | Hardcoded internal timeout |
| `request_ctx` (ContextVar) | `server/lowlevel/server.py` | Internal context propagation |
| `StructuredContent` | `server/lowlevel/server.py` | Internal type alias |
| `UnstructuredContent` | `server/lowlevel/server.py` | Internal type alias |
| `CombinationContent` | `server/lowlevel/server.py` | Internal type alias |
| `Settings` | `server/mcpserver/server.py` | Internal config class |
| `lifespan_wrapper` | `server/mcpserver/server.py` | Internal helper |
| `remove_request_params` | `client/sse.py` | Internal URL helper |
| All `MCP_SESSION_ID`, `MCP_PROTOCOL_VERSION`, `LAST_EVENT_ID` constants | transport modules | Internal protocol constants |
| `SessionMessageOrError`, `StreamWriter`, `StreamReader`, `GetSessionIdCallback` | `client/streamable_http.py` | Internal type aliases |
| `RequestContext` (dataclass) | `client/streamable_http.py` | Collides with `shared.context.RequestContext`; internal |

---

## Needs-Decision Items

These require an explicit team call. They are ambiguous and have arguments on both sides.

| Item | Location | Question |
|---|---|---|
| `get_default_environment()` | `client/stdio.py` | Do users need to call this? Or just customize `StdioServerParameters.env`? |
| `DEFAULT_INHERITED_ENV_VARS` | `client/stdio.py` | Same — users might want to reference the default list |
| `ToolManager`, `ResourceManager`, `PromptManager` | `server/mcpserver/` sub-packages | Currently exported. Do users need these directly, or is `MCPServer.add_tool()` sufficient? |
| `StreamableHTTPTransport` | `client/streamable_http.py` | Do users need the transport class directly for advanced customization? |
| `StreamableHTTPServerTransport` | `server/streamable_http.py` | Same question, server side |
| `MCPServerError` and subclasses | `server/mcpserver/exceptions.py` | Should users be able to `except MCPServerError`? Probably yes — add to Tier 1 |
| `RequestResponder` | `shared/session.py` | Needed if `ServerSession.incoming_messages` is public. Is it? |
| `BaseSession` | `shared/session.py` | Should advanced users subclass? Likely no |

---

## Implementation Phases

### Phase 0: Tooling & Allowlist (do first, blocks everything else)

- Write `scripts/audit_public_api.py` using `griffe` to enumerate the live surface
- Generate `docs/public_api_allowlist.txt` from the Tier tables above
- Wire the audit script into CI (can add as a ruff-style pre-commit hook or a dedicated CI step)
- Resolve the "Needs-Decision" items and update the allowlist

### Phase 1: Module Renames (one large batch)

- Rename all implementation modules as specified in the tables above
- Update all internal imports across `src/mcp/`
- Update all `__init__.py` re-exports to point to new `_`-prefixed paths
- Update all test imports
- Run the full test suite; fix any breakage

### Phase 2: `__init__.py` Surface Consolidation

- Add missing re-exports (transport functions, auth types, elicitation types, callback protocols) to the appropriate `__init__.py` files
- Ensure every `__init__.py` has `__all__`
- Verify stable import paths match the allowlist tables

### Phase 3: Internal Name Cleanup

- Prefix internal constants, type aliases, and helpers with `_` as specified in the "Internal Names" table
- Resolve the `RequestContext` name collision
- Run pyright; verify no new `reportPrivateUsage` warnings from tests

### Phase 4: Type Stubs (optional, long-term)

- Generate `.pyi` stubs covering only the public surface
- Check them into the repo
- Review stub diffs in PRs as an API review signal
