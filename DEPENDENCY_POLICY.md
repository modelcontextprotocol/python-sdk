# Dependency Policy

As a library consumed by downstream projects, the MCP Python SDK takes a conservative approach to dependency updates. Dependencies are kept stable unless there is a specific reason to update, such as a security vulnerability, a bug fix, or a need for new functionality.

## Update Triggers

Dependencies are updated when:

- A **security vulnerability** is disclosed (via GitHub security alerts or PyPI advisories) in a dependency that directly affects the SDK's functionality or its consumers.
- A bug in a dependency directly affects the SDK.
- A new dependency feature is needed for SDK development.
- A dependency drops support for a Python version the SDK still targets.

Routine version bumps without a clear motivation are avoided to minimize churn for downstream consumers.

## What We Don't Do

The SDK does not run ad-hoc version bumps for PyPI dependencies. Updating a dependency can force downstream consumers to adopt that update transitively, which can be disruptive for projects with strict dependency policies.

Dependencies are only updated when there is a concrete reason, not simply because a newer version is available.

## Automated Tooling

- **Lockfile refresh**: The lockfile is updated automatically every Thursday at 08:00 UTC by the [`weekly-lockfile-update.yml`](.github/workflows/weekly-lockfile-update.yml) workflow, which runs `uv lock --upgrade` and opens a PR. This does not alter the minimum or maximum versions for dependencies of the `mcp` package itself.
- **GitHub security updates** are enabled at the repository level and automatically open pull requests for packages with known vulnerabilities. This is a GitHub repo setting, separate from the `dependabot.yml` configuration.
- **GitHub Actions versions** are kept up to date via Dependabot on a monthly schedule (see `.github/dependabot.yml`).

## Pinning and Ranges

Production dependencies use compatible-release specifiers (`~=`) or lower-bound constraints (`>=`) to allow compatible updates. Exact versions are pinned only when necessary to work around a specific issue. The lockfile (`uv.lock`) records exact resolved versions for reproducible installs.
