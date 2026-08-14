# Dependency Policy

`mcp` is a library that lives inside other people's environments, so its dependency requirements are chosen to constrain your resolver as little as possible while still describing what the SDK actually needs.

## How requirements are declared

* **Floors, not pins.** Every runtime dependency is a `>=` lower bound, set to the oldest version that provides what the SDK uses. There are no upper bounds unless a dependency's next major version is known to break the SDK.
* **The one exception is `mcp-types`.** The wire-types package is developed and released with `mcp` in lockstep, so `mcp` requires exactly its own version (`mcp-types==<same version>`). It is not an independent constraint on your environment; it is the other half of the SDK.
* **Environment markers instead of parallel packages** — Python-version and platform differences (`python_version`, `sys_platform`) are expressed as markers on the requirement, so one wheel serves every supported environment.
* **Add-on tooling is an extra.** The command-line tooling and rich console output live behind extras (`mcp[cli]`, `mcp[rich]`); the client, the server, the HTTP transport stack, and auth support are all part of the base install by design.

## When a floor moves

A minimum version is raised only when the SDK starts relying on functionality, a fix, or an API that first appeared in that version. It is not raised because a dependency published a security advisory. The `>=` bound already lets — and expects — you to run the newest release your other constraints allow, so a higher floor would only shrink the set of environments the SDK installs into without changing what any correctly-updated environment resolves to. The SDK also does not add code to work around a vulnerability in a dependency; the fix belongs upstream and in your lockfile. ([Background](https://github.com/Kludex/uvicorn/discussions/2643) on this stance from another library that adopted it, and [python-sdk#1552](https://github.com/modelcontextprotocol/python-sdk/issues/1552).)

The floors are also tested continuously rather than only when they are set: CI runs the test suite against a `lowest-direct` resolution as well as the locked set, on every supported Python version.

Raising a floor is a minor-release change, called out in the release notes; the [versioning policy](https://py.sdk.modelcontextprotocol.io/versioning/) is the authority on what may ship in which kind of release. Adding a new required runtime dependency, or moving an existing one to its next major version, is a maintainer decision made in an issue before the pull request, not a side effect of a feature.

## Automated updates

[Dependabot](https://github.com/modelcontextprotocol/python-sdk/blob/main/.github/dependabot.yml) opens monthly, grouped pull requests for the `uv` lockfile and for GitHub Actions, with a 14-day cooldown on newly published versions. These refresh the versions the SDK is developed and tested against (`uv.lock`); they never change the requirements published to PyPI, which move only under the rules above.

## Security in the SDK itself

Vulnerabilities in the SDK's own code — as opposed to its dependencies — follow the reporting process in [SECURITY.md](https://github.com/modelcontextprotocol/python-sdk/blob/main/SECURITY.md).
