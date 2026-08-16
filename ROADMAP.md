# Roadmap

The SDK's work is organized by MCP specification revision, with one GitHub project board per revision; each item is an issue or pull request you can follow.

## The 2026-07-28 revision

v2 implements the [2026-07-28 specification](https://modelcontextprotocol.io/specification/2026-07-28) and negotiates back to every earlier revision. Board: **[python-sdk · 2026-07-28 spec](https://github.com/orgs/modelcontextprotocol/projects/42)**; the cross-SDK view is [2026-07-28 Spec Implementation](https://github.com/orgs/modelcontextprotocol/projects/41). Still open there: making advertised capabilities configurable rather than pre-computed ([#2896](https://github.com/modelcontextprotocol/python-sdk/issues/2896)).

## Not yet implemented

Of the extensions and optional client-auth mechanisms not yet implemented, those the conformance suite already exercises appear in its expected-failures baseline, [`.github/actions/conformance/expected-failures.yml`](.github/actions/conformance/expected-failures.yml), which burns down as each lands. The main ones:

* **Tasks extension** (`io.modelcontextprotocol/tasks`, [SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2663-tasks-extension.md)) — deferred at 2.0 because the 2026-07-28 design is wire-incompatible with the earlier in-core Tasks; tracked in [#2806](https://github.com/modelcontextprotocol/python-sdk/issues/2806).
* **DPoP-bound access tokens** ([SEP-1932](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1932)) in the OAuth client.
* **The workload-identity `jwt-bearer` grant** in the OAuth client.

Everything else — bugs and smaller features — lives in the [issue tracker](https://github.com/modelcontextprotocol/python-sdk/issues), prioritized `P0`–`P3`. The SDK aims to release support for each new specification revision alongside that revision.

## The previous major

`v1.x` is a maintenance line: critical bug fixes and security fixes only. Support terms are in [Versioning and support policy](VERSIONING.md#support-and-announcements); the path off it is the **[Migration Guide](https://py.sdk.modelcontextprotocol.io/migration/)**.
