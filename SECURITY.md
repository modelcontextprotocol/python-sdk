# Security Policy

Thank you for helping keep the Model Context Protocol and its ecosystem secure.

## Supported Versions

| Version                              | Line                    | Support                                  |
| ------------------------------------ | ----------------------- | ---------------------------------------- |
| 2.x (newest release)                 | current stable (`main`) | bug fixes, security fixes, new features  |
| 1.28.x (`v1.x` branch)               | maintenance             | critical bug fixes and security fixes    |
| < 1.28, and all pre-release versions | unsupported             | upgrade to the newest 1.28.x or to 2.x   |

Only the newest release of a supported line receives fixes, so reproduce against
it before reporting. If your project depends on `mcp` and is not yet ready for
2.x, constrain to `mcp>=1.28,<2` and follow the
[migration guide](https://py.sdk.modelcontextprotocol.io/migration/) when you
migrate.

## Reporting Security Issues

If you discover a security vulnerability in this repository, please report it through
the [GitHub Security Advisory process](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
for this repository.

Please **do not** report security vulnerabilities through public GitHub issues, discussions,
or pull requests.

## What to Include

To help us triage and respond quickly, please include:

- A description of the vulnerability
- Steps to reproduce the issue
- The potential impact
- Any suggested fixes (optional)
