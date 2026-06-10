# Release Process

## Bumping Dependencies

1. Change dependency version in `pyproject.toml`
2. Upgrade lock with `uv lock --resolution lowest-direct`

## Major or Minor Release

Create a GitHub release via UI with the tag being `vX.Y.Z` where `X.Y.Z` is the version,
and the release title being the same. Then ask someone to review the release.

The package version will be set automatically from the tag.

## v2 Pre-releases

v2 pre-releases are cut from `main` with a PEP 440 pre-release tag: `v2.0.0aN`
for alphas, later `bN`/`rcN` for betas and release candidates.

1. Check the full test matrix is green on the release commit. The matrix runs
   with `continue-on-error`, so a green workflow run does not mean the tests
   passed — check the individual jobs.
2. Create the release as a pre-release, passing the exact commit verified in
   step 1 as `--target` (otherwise the tag is created from whatever `main`'s
   HEAD is by then). The pre-release flag keeps GitHub's "Latest" badge and
   `/releases/latest` pointing at the stable v1.x line:

   ```shell
   gh release create v2.0.0aN --prerelease --title v2.0.0aN --target <commit-sha>
   ```

3. Curate the release notes instead of relying on auto-generated ones: what
   changed since the previous pre-release, what is known-incomplete, the
   install line (`pip install mcp==2.0.0aN`), and a link to the
   [migration guide](docs/migration.md).
4. If a pre-release turns out to be broken, yank it on PyPI and cut the next
   one. Never delete a release from PyPI — version numbers cannot be reused.
