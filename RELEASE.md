# Release Process

## Bumping Dependencies

1. Change dependency version in `pyproject.toml`
2. Upgrade lock with `uv lock --resolution lowest-direct`

## Major or Minor Release

Create a GitHub release via UI with the tag being `vX.Y.Z` where `X.Y.Z` is the version,
and the release title being the same. Then ask someone to review the release.

The package version will be set automatically from the tag.
