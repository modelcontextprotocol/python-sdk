# Dependency Policy

`mcp` is a library that lives inside other people's environments, so its requirements are chosen to constrain your resolver as little as possible while still describing what the SDK needs.

## How requirements are declared

Every runtime dependency is a `>=` floor set to the oldest version that provides what the SDK uses, with no upper bound unless a dependency's next major is known to break the SDK. The one exception is `mcp-types`, the wire-types package released in lockstep with `mcp`: each `mcp` release requires exactly its own version of it, so it is the other half of the SDK rather than an independent constraint.

## When a floor moves

A floor is raised only when the SDK starts relying on functionality or a fix that first appeared in that version — not because the dependency published a security advisory. The `>=` bound already lets, and expects, you to run the newest release your other constraints allow, so a higher floor would only shrink the environments the SDK installs into; nor does the SDK add code to work around a dependency's vulnerability, since the fix belongs upstream and in your lockfile ([background](https://github.com/Kludex/uvicorn/discussions/2643), [python-sdk#1552](https://github.com/modelcontextprotocol/python-sdk/issues/1552)). Floor raises may ship in a minor release under the [versioning policy](VERSIONING.md) and are called out in the release notes. Adding a new runtime dependency, or moving one to its next major version, is decided in an issue before the pull request.

## Automated updates

[Dependabot](https://github.com/modelcontextprotocol/python-sdk/blob/main/.github/dependabot.yml) opens monthly, grouped pull requests for the `uv` lockfile and for GitHub Actions. These refresh the versions the SDK is developed and tested against; the requirements published to PyPI move only under the rules above.
