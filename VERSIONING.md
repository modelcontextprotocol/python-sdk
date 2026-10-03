# Versioning and support policy

What a version number of `mcp` promises: which changes can arrive in a minor release, which wait for a major, how deprecations are announced, and which release lines are supported.

## The version number

[Semantic Versioning](https://semver.org/) semantics in [PEP 440](https://peps.python.org/pep-0440/) syntax, taken from the git tag: in `2.X.Y`, **X** (minor) carries new functionality and every non-breaking change, **Y** (patch) carries bug fixes only, and a breaking change to the public API lands only in a new **major**. Pre-releases are cut from `main` as `aN`/`bN`/`rcN`; installers prefer final releases by default, so an unpinned `pip install mcp` stays on a stable release whenever one satisfies your requirement. `mcp` and its wire-types package `mcp-types` release in lockstep, each `mcp` requiring exactly the matching `mcp-types`.

## The public API

The promise covers every name exported by `mcp` and `mcp_types` (their `__all__`), the import paths, signatures, and behavior documented on the [documentation site](https://py.sdk.modelcontextprotocol.io/) and in its [API Reference](https://py.sdk.modelcontextprotocol.io/api/mcp/). It does not cover underscore-prefixed names, undocumented modules, or the wording of log lines, warnings, and exception messages (their types and documented raise conditions are covered). APIs labelled **provisional** (for example the middleware chain) may still change in a minor release; **experimental** APIs are opt-in previews.

## Breaking and non-breaking changes

Held for the next major:

* removing or renaming a public name,
* changing a signature, return type, raised exception type, or documented behavior so that working code stops working,
* removing a documented import path, extra, or CLI command.

Allowed in a minor:

* additions — functions, defaulted parameters, classes, fields, enum members,
* changes to provisional or experimental APIs,
* new deprecation warnings, and retired protocol features ceasing to work on connections that negotiate a revision without them (their Python names stay, deprecated, until a major),
* raising a dependency floor the SDK needs (see the [dependency policy](DEPENDENCY_POLICY.md)) when the dependency's changes don't reach you through the SDK's API, or dropping a Python version after its upstream end-of-life — both called out in the release notes,
* bug fixes, including ones that make the SDK match its documented or specified behavior.

## Deprecations

**SDK APIs** are deprecated before removal: they keep working for at least one minor release, marked with [`typing_extensions.deprecated`](https://typing-extensions.readthedocs.io/en/latest/#typing_extensions.deprecated) wherever Python can carry the marker (docstring and migration guide otherwise), and are removed only in a major. **Protocol features** the specification retires keep their implementation through the spec's deprecation window and warn with `MCPDeprecationWarning`, a `UserWarning` subclass that shows by default; what still functions depends on the revision a connection negotiated — see [Deprecated features](https://py.sdk.modelcontextprotocol.io/deprecated/).

## Support and announcements

Two lines are maintained, and only the newest release of each receives fixes:

* **2.x** (`main`) — bug fixes, security fixes, and features.
* **1.x** ([`v1.x`](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)) — critical bug fixes and security fixes.

Where changes are announced:

* [SECURITY.md](https://github.com/modelcontextprotocol/python-sdk/blob/main/SECURITY.md) has the vulnerability reporting process.
* Every release publishes notes on [GitHub Releases](https://github.com/modelcontextprotocol/python-sdk/releases).
* Every breaking change between majors is documented in the [Migration Guide](https://py.sdk.modelcontextprotocol.io/migration/) before it merges.
* Pull requests that make a breaking change carry the `breaking change` label.
