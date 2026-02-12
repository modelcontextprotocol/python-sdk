# Versioning Policy

## Versioning Scheme

The MCP Python SDK follows [Semantic Versioning 2.0.0](https://semver.org/):

- **Major** (X.0.0): Breaking changes to the public API
- **Minor** (0.X.0): New features, backward-compatible additions
- **Patch** (0.0.X): Bug fixes, backward-compatible corrections

## What Constitutes a Breaking Change

The following are considered breaking changes and require a major version bump:

- Removing or renaming a public function, class, method, or module
- Changing the signature of a public function or method in a non-backward-compatible way (removing parameters, changing required parameters, changing return types)
- Changing the behavior of a public API in a way that existing callers would not expect
- Dropping support for a Python version
- Changing the minimum required version of a dependency in a way that is incompatible with previously supported ranges
- Removing or renaming protocol message types or fields from the public schema

The following are **not** considered breaking changes:

- Adding new optional parameters with default values
- Adding new public functions, classes, or methods
- Adding new fields to response types
- Deprecating (but not removing) existing APIs
- Changes to private/internal APIs (prefixed with `_`)
- Bug fixes that correct behavior to match documented intent
- Adding support for new protocol versions while maintaining backward compatibility

## How Breaking Changes Are Communicated

1. **Deprecation warnings**: Before removal, public APIs are deprecated for at least one minor release with `DeprecationWarning` and migration guidance.
2. **Release notes**: All breaking changes are documented in GitHub Release notes with migration instructions.
3. **PR labels**: Pull requests containing breaking changes are labeled accordingly.

## Release Branches

- **`main`**: Development branch for the next major version
- **`v1.x`**: Stable release branch for the 1.x series; receives bug fixes and backward-compatible features
- **`v1.Y.x`** (e.g., `v1.7.x`): Patch release branches for specific minor versions when needed

Bug fixes target the latest release branch and are forward-merged into `main`. New features target `main` and may be backported to the release branch if appropriate.

## Protocol Version Tracking

The SDK tracks the MCP specification. When a new spec version is released, the SDK targets a corresponding release within 30 days. Protocol version support is documented in the README.
