# Versioning and support policy

This page states what a version number of the `mcp` package promises you: which changes can arrive in a minor release, which are held for the next major, how deprecations are announced, and how long each release line is supported.

## The version number

Releases follow [Semantic Versioning](https://semver.org/) semantics, written in [PEP 440](https://peps.python.org/pep-0440/) syntax:

* **`2.X.Y`** — the version comes from the git tag; there is no version field to edit.
* **`X` (minor)** — new functionality and every non-breaking change.
* **`Y` (patch)** — bug fixes only.
* **The leading `2` (major)** — the only place a breaking change to the public API can land.
* **Pre-releases** are cut from `main` as `2.X.YaN` (alpha), `2.X.YbN` (beta), and `2.X.YrcN` (release candidate). Installers never select a pre-release unless you ask for one, by exact pin or `--pre`.

`mcp` and its wire-types package [`mcp-types`](https://pypi.org/project/mcp-types/) release in lockstep at the same version: each `mcp` release requires exactly the matching `mcp-types` (`mcp-types==2.X.Y`).

## What the public API is

The compatibility promise covers the public API:

* every name exported by `mcp` (its `__all__`) and by `mcp_types`,
* the import paths, classes, functions, and parameters documented on this site and in the [API Reference](api/mcp/index.md),
* documented behavior of those APIs.

It does not cover names beginning with an underscore, modules and attributes that appear nowhere in the documentation, or the exact text of log lines, warnings, and exception messages (their *type* and the documented conditions that raise them are covered; their wording is not). Depending on one of those is depending on an implementation detail that may change in any release.

Two labels mark APIs that sit outside the promise while they settle:

* **Provisional** — shipped and supported, but the signature or semantics may still change in a minor release. The middleware chain is the current example, and its documentation says so.
* **Experimental** — behind an explicit opt-in and expected to change; treat it as a preview.

## What counts as a breaking change

These wait for the next major version:

* removing or renaming a public name,
* changing a signature so that a call that worked stops working (a removed or reordered parameter, a newly required argument, a narrowed accepted type),
* changing a return type, a raised exception type, or documented behavior in a way existing callers would notice,
* removing a documented import path, extra, or CLI command.

These do not, and can ship in a minor release:

* new functions, parameters with defaults, classes, fields, and enum members,
* changes to provisional or experimental APIs,
* new deprecation warnings, and the eventual removal of a protocol feature the specification has retired (see [Deprecations](#deprecations)),
* raising a dependency's minimum version when the SDK needs newer functionality, or dropping a Python version that upstream has ended support for — both called out in the release notes (the [dependency policy](https://github.com/modelcontextprotocol/python-sdk/blob/main/DEPENDENCY_POLICY.md) covers the first),
* bug fixes, including fixes that make the SDK match documented or specified behavior it should have had all along.

When a fix is arguably both a bug fix and a behavior change, the deciding question is whether reasonable code written against the *documented* behavior breaks. If it does, the change is breaking.

## Deprecations

There are two kinds, warned differently on purpose.

**SDK API deprecations** — a name or parameter this SDK is retiring. The API keeps working, marked with [`typing_extensions.deprecated`](https://typing-extensions.readthedocs.io/en/latest/#typing_extensions.deprecated), so static type checkers flag every call site and Python emits a `DeprecationWarning` at runtime. A deprecated API survives at least one minor release with its warning in place, and is removed only in a major version: something deprecated during 2.x is not removed before 3.0.

**Protocol deprecations** — a feature the MCP specification has retired (for example the SEP-2577 set in the 2026-07-28 revision). These keep working through the specification's deprecation window and warn with `MCPDeprecationWarning`, a `UserWarning` subclass, so the warning is visible by default rather than hidden the way `DeprecationWarning` is outside `__main__`. **[Deprecated features](deprecated.md)** lists every one, its replacement, and how to silence the warning when you genuinely serve older clients.

## Supported release lines

Two lines are maintained, and only the newest release of a line receives fixes:

| Line | Branch | Receives |
| --- | --- | --- |
| 2.x — current stable | `main` | bug fixes, security fixes, new features |
| 1.x — maintenance | [`v1.x`](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x) | critical bug fixes and security fixes |

Older 1.x releases and all pre-releases are unsupported. The security-specific version of this table, and how to report a vulnerability, is in [SECURITY.md](https://github.com/modelcontextprotocol/python-sdk/blob/main/SECURITY.md). Still on 1.x? Its documentation is at [/v1/](https://py.sdk.modelcontextprotocol.io/v1/), and a `<2` upper bound on your `mcp` requirement keeps an unpinned resolve on that line until you migrate.

Python versions are supported from the version in the package's `requires-python` up to the newest CPython release the test suite runs against; support for a Python version ends only after that version's upstream end-of-life.

## Where changes are announced

* **Release notes** — every release publishes curated notes on [GitHub Releases](https://github.com/modelcontextprotocol/python-sdk/releases): highlights, anything known-incomplete, and a full change list. Pre-releases say what changed since the previous pre-release.
* **The migration guide** — every breaking change between majors is documented in **[Migration Guide](migration.md)** with before-and-after code; a change is not merged for a major release without its entry.
* **The `breaking change` label** — pull requests that make a breaking change carry it, so the set is queryable ahead of a major release.
* **Deprecation warnings** — as above, one release of warning at minimum before an SDK API is removed.
