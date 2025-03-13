# Release Process

## Bumping Dependencies

1. Change dependency
2. Upgrade lock with `uv lock --resolution lowest-direct`

## Major or Minor Release

1. Create a release branch named `vX.Y.Z` where `X.Y.Z` is the version.
2. Bump version number on release branch.
3. Create an annotated, signed tag: `git tag -s -a vX.Y.Z`
4. Create a github release using `gh release create` and publish it.
5. Have the release flow being reviewed.
7. Bump version number on `main` to the next version followed by `.dev`, e.g. `v0.4.0.dev`.
