# Roadmap

The SDK's job is to implement the MCP specification, so its roadmap is organized by specification revision: one GitHub project board per revision, each item an issue or pull request you can follow. This page names the board that is current, what remains open on it, and the maintenance stance for the previous major.

## The 2026-07-28 revision — shipped, with follow-ups

v2 implements the [2026-07-28 specification](https://modelcontextprotocol.io/specification/2026-07-28) (and negotiates back to every earlier revision — see [Protocol versions](protocol-versions.md)); **[What's new in v2](whats-new.md)** is the tour of what that meant for the SDK.

* Board: **[python-sdk · 2026-07-28 spec](https://github.com/orgs/modelcontextprotocol/projects/42)**, tracking issue [#2891](https://github.com/modelcontextprotocol/python-sdk/issues/2891).
* Cross-SDK view: [2026-07-28 Spec Implementation](https://github.com/orgs/modelcontextprotocol/projects/41) tracks the same revision across all official SDKs.

Open on that board:

* **Capabilities API and the `server/discover` handler** — the last core item still in progress ([#2896](https://github.com/modelcontextprotocol/python-sdk/issues/2896)).

## Extensions and optional client auth not yet implemented

The 2026-07-28 revision moved some functionality out of the core protocol into named extensions, and defines client-side auth mechanisms an SDK may support. The ones this SDK does not implement yet are tracked as the entries in the conformance suite's expected-failures baseline, [`.github/actions/conformance/expected-failures.yml`](https://github.com/modelcontextprotocol/python-sdk/blob/main/.github/actions/conformance/expected-failures.yml) — that file is grouped by SEP and each entry is removed as the corresponding work lands, so it is the live burn-down list:

* **Tasks extension** (`io.modelcontextprotocol/tasks`, [SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2663-tasks-extension.md)) — deferred at 2.0 because the 2026-07-28 design is wire-incompatible with the earlier in-core Tasks; tracked in [#2806](https://github.com/modelcontextprotocol/python-sdk/issues/2806).
* **DPoP-bound access tokens** ([SEP-1932](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1932)) in the OAuth client.
* **The workload-identity `jwt-bearer` grant** in the OAuth client.

None of these blocks a release — each is carried as an expected failure in that baseline until it lands — but each is a real gap for anyone who needs the feature, and together they are the current queue.

## Continuous work

* **Conformance** — every pull request and every push to `main` runs the [conformance suite](https://github.com/modelcontextprotocol/conformance) as both server and client, against the released revisions and against the 2026-07-28 wire specifically; adopting each new harness release and reconciling its baseline is routine.
* **The next specification revision** — draft-only wire changes are tried behind the draft protocol version before they are final, and land in a release once the revision ships; the SDK targets releasing support alongside each new specification version.
* **Everything else** — the [issue tracker](https://github.com/modelcontextprotocol/python-sdk/issues) is the source of truth for bugs and smaller features; `P0`–`P3` labels carry priority.

## The previous major

`v1.x` is a maintenance line: critical bug fixes and security fixes only, no new features. Its documentation stays available at [/v1/](https://py.sdk.modelcontextprotocol.io/v1/), the support terms are in [Versioning and support policy](versioning.md#supported-release-lines), and the path off it is the **[Migration Guide](migration.md)**.
