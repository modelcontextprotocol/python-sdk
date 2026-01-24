# MCP Extensibility Research: Complete Findings

## The Foundational Quote

From **@jspahrsummers** (MCP co-creator) on [PR #185](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/185) (ToolAnnotations):

> "All objects in the MCP spec are intentionally open-ended, so it's always possible to add custom fields that only your server and client implementations understand. (No forking required!)"

This is the design intent. The reality in the SDKs is more nuanced.

---

## 1. Extra Fields on Types

**Spec-level intent:** All types are open-ended. The schema.ts has `[key: string]: unknown` on `Result`, and `params?: { [key: string]: any }` on `Request` with a comment: "Allow unofficial extensions of `Request.params` without impacting `RequestParams`."

**Active debate:** [Issue #1898](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1898) — "Clarify extensibility intent by adding `additionalProperties: false` to closed types"

Key positions in that thread:

- **@pja-ant** (Anthropic): "The main thing is that clients/servers should not break if there's extra fields received in requests on the wire. This is just a simple P0 requirement to support inter-version compatibility... I don't think SDKs have to expose the ability to insert new fields though (beyond perhaps `_meta` / `experimental`)."
- **@mikekistler**: Notes Justin's comment predates formalized extensions — "Now that we have extensions... that seems like the right mechanism for adding custom fields."
- **@maxisbey**: "I agree that SDKs shouldn't break if they receive objects with added fields they don't recognise. As for allowing users of the SDKs to add arbitrary fields to types without forking I think this could be valuable."
- **@felixweinberger**: TS SDK uses Zod `.strip()` (silently drops unknowns) — old servers ignore new fields naturally.

**Python SDK reality:**

- [PR #1937](https://github.com/modelcontextprotocol/python-sdk/pull/1937) (merged 2026-01-23, by Kludex) **removed `extra="allow"` from `MCPModel`**. Types now reject/ignore extra fields, matching the TS SDK's `.strip()` behavior.
- Exception: `GetTaskPayloadResult` retains `extra="allow"` (dynamic result structure).
- `RequestParamsMeta` uses `extra_items=Any` to preserve extra `_meta` keys.

**TypeScript SDK reality:**

- [PR #1242](https://github.com/modelcontextprotocol/typescript-sdk/pull/1242) (merged) removed `.passthrough()` from all types. Now uses `.strip()` (silently drops unknowns).
- This broke real users: [PR #1144](https://github.com/modelcontextprotocol/typescript-sdk/pull/1144) — Cloudflare's x402 integration extended `ToolAnnotations` with `paymentHint`/`paymentPriceUSD` fields, which stopped working.

**Consensus:** SDKs MUST tolerate unknown fields on the wire (don't throw). Whether SDKs should *expose* the ability to *add* custom fields is unresolved — `_meta` and `experimental` are the current blessed extension points.

---

## 2. Custom Request Methods

This is the less-settled half of the extensibility story.

**Protocol level:** `Request` has `method: string` — any method string is valid JSON-RPC.

**Python SDK barriers** (from code analysis):

- `ClientRequest` / `ServerRequest` are **hardcoded `TypeAdapter` discriminated unions**. Unknown methods fail validation with `INVALID_PARAMS` before reaching any handler.
- No public API to register handlers for custom request types.
- The `request_handlers: dict[type, Callable]` in `LowLevelServer` is keyed by type — custom types can't arrive because the `TypeAdapter` rejects them first.

**TypeScript SDK:** Has `fallbackRequestHandler` and `fallbackNotificationHandler` on the `Protocol` base class — a catch-all for unrecognized methods. Also supports type generics on `Server<RequestT, NotificationT, ResultT>`. Much more extensible than the Python SDK here.

**Python SDK attempts:**

- [PR #535](https://github.com/modelcontextprotocol/python-sdk/pull/535) — "Custom MCP requests + hooks" (closed, not merged). Used a `custom/request` wrapper method. Maintainer feedback from **@jerome3o-anthropic**: "Ideally they would be able to have their own method defined at that root level, as opposed to in the params." **@dsp-ant**: "I still think this is an important feature, but we should implement this with the ability to specify custom request method names."
- [Issue #1399](https://github.com/modelcontextprotocol/python-sdk/issues/1399) — P1 bug: Custom notifications (e.g., `codex/event` from Codex) cause validation errors because `ServerNotification` is a closed union.
- [PR #1911](https://github.com/modelcontextprotocol/python-sdk/pull/1911) — Message middleware for session message transformation (closed). Was exploring a middleware pattern to intercept/transform JSON-RPC messages.

---

## 3. The `_meta` Mechanism

**Spec status:** Formalized in the draft spec with a vendor prefix naming convention:

- Key format: optional reverse-DNS prefix + name (e.g., `com.example/my-key`)
- Prefixes where the second label is `modelcontextprotocol` or `mcp` are **reserved**
- Already used for `progressToken`

**Key issues:**

- [PR #414](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/414) — Formalizing `_meta` for OTel context propagation (open, seeking sponsor). Debate over `request.params._meta` (current) vs top-level `request._meta` (cleaner but breaking).
- [Issue #264](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/264) — Namespace collision concern: `progressToken` isn't namespaced, so if a vendor happened to use that key it would collide. **@domdomegg** proposed moving it to `modelcontextprotocol.io/progressToken`.
- [SEP-1788](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1788) — Clarify `_meta` reserved keys (open, sponsored by @tadasant).

**Python SDK:** [PR #1231](https://github.com/modelcontextprotocol/python-sdk/pull/1231) (merged) exposed `_meta` as a `dict` parameter on `call_tool()` and other session methods.

---

## 4. The `experimental` Capabilities Field

Already exists in both `ClientCapabilities` and `ServerCapabilities`:

```typescript
experimental?: { [key: string]: object };
```

The schema comment says: "Known capabilities are defined here, in this schema, but this is not a closed set: any client can define its own, additional capabilities."

**@jspahrsummers** closed [PR #69](https://github.com/modelcontextprotocol/python-sdk/pull/69) confirming the loose typing of `experimental` was intentional per the spec.

---

## 5. The Extensions Framework (SEP-1724 → PR #2133)

This is the formal proposal for how extensions work in MCP.

**Original issue:** [#1724](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1724) (closed)
**Current PR:** [#2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133) (open, in-review)
**Author:** @pja-ant (Peter Alexander, Anthropic). **Sponsor:** @pcarleton

**Design:**

- Extension identifiers use reverse DNS: `io.modelcontextprotocol/oauth-client-credentials`
- Official extensions live in `github.com/modelcontextprotocol/ext-*` repos
- New `extensions` field in `ClientCapabilities`/`ServerCapabilities` — map of extension ID → settings object
- Extensions MUST be disabled by default, require explicit opt-in
- Breaking changes require a new identifier (e.g., append `-v2`)

**Core maintainers initially rejected** the first version (dsp-ant):
> "Core Maintainers did not approve this for now. The common understanding... was that this requires more detail: For official extensions: clarity on trademarks, antitrust, etc. The governing structure... needs clarification. The recommended tier would require a lot more detail on lifecycle. There are concerns how capabilities and versioning will work."

PR #2133 is the revised version addressing these concerns.

**Existing extension repos already created:**

- `ext-auth` — OAuth/auth extensions
- `ext-apps` — MCP Apps/UI extension

**SDK tracking issues:**

- Python SDK: [#1555](https://github.com/modelcontextprotocol/python-sdk/issues/1555) (pending SEP approval)
- TypeScript SDK: [#1063](https://github.com/modelcontextprotocol/typescript-sdk/issues/1063) (pending SEP approval)

---

## 6. Extension Negotiation and Versioning (Unsolved)

**[SEP-1849](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1849) — Extension Negotiation:**

- @pja-ant raised that different extension types need fundamentally different negotiation: transport extensions need pre-init, auth extensions happen outside the data plane, only post-init feature extensions could use init-time negotiation.
- Leaning toward "let each extension define its own negotiation semantics" rather than a generic framework.

**[SEP-1848](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1848) — Extension Versioning:**

- Debate over semver vs major.minor only. Whether version goes in the capability key (`com.example/ext/1.1`) is unresolved.

**[SEP-1381](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1381) — Utilized Capability Declarations:**

- Proposes that clients declare which *server* capabilities they can consume (not just their own). Strong community support but stalled.

---

## 7. Roadmap

The [official roadmap](https://modelcontextprotocol.io/development/roadmap.md) explicitly lists **"Official Extensions"** as a priority area:
> "As MCP has grown, valuable patterns have emerged for specific industries and use cases. Rather than leaving everyone to reinvent the wheel, we're officially recognizing and documenting the most popular protocol extensions."

---

## 8. SEP-1319: Decoupling Payloads from RPC Methods

[SEP-1319](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/1319) (status: Final) refactors the spec to separate data payloads from JSON-RPC method definitions. Motivation includes enabling alternative transports (gRPC) and cleaner extensibility. The Python SDK [already does this](https://github.com/modelcontextprotocol/python-sdk/issues/1541) (`CallToolRequestParams` is separate from `CallToolRequest`).

---

## Summary Table

| Aspect | Spec Intent | Python SDK | TypeScript SDK |
|---|---|---|---|
| **Extra fields on types** | All objects open-ended (jspahrsummers) | Stripped/ignored since PR #1937 | Stripped via `.strip()` since PR #1242 |
| **`_meta` for custom data** | Formalized with reverse-DNS prefixes | Exposed on session methods (PR #1231) | Available via `RequestHandlerExtra` |
| **`experimental` capabilities** | `{ [key: string]: object }`, intentionally loose | Exists, usable | Exists, usable |
| **Custom request methods** | `method: string` — any method valid | **Blocked** — closed `TypeAdapter` unions reject unknowns | Supported via `fallbackRequestHandler` + type generics |
| **Custom notifications** | Same as above | **Broken** — P1 issue #1399 | Supported via `fallbackNotificationHandler` |
| **Extensions framework** | SEP-2133 in-review, `extensions` field in capabilities | Tracking issue #1555, pending SEP | Tracking issue #1063, pending SEP |
| **Extension negotiation** | Unsolved — leaning toward per-extension semantics | N/A | N/A |

## Key Takeaway for Python SDK v2

The fundamental barrier to extensibility in the Python SDK is that `ClientRequest`/`ServerRequest`/`ClientNotification`/`ServerNotification` are **statically defined discriminated unions** validated by `TypeAdapter` before any handler dispatch. To support custom methods, the SDK needs either:

1. A way to extend these unions at runtime, or
2. A fallback path (like the TS SDK's `fallbackRequestHandler`) that passes raw/unvalidated requests to custom handlers

This is acknowledged as important by maintainers (dsp-ant on PR #535: "I still think this is an important feature") but unimplemented.
