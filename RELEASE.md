# Release Process

## Bumping Dependencies

1. Change the dependency version in `pyproject.toml`. The root `mcp` project's
   runtime dependencies are dynamic and live under
   `[tool.hatch.metadata.hooks.uv-dynamic-versioning].dependencies`.
2. Upgrade lock with `uv lock --resolution lowest-direct`

## Major or Minor Release

Stable releases are cut from the `v1.x` branch. Create a GitHub release via UI
with the tag being `vX.Y.Z` where `X.Y.Z` is the version and the release title
being the same, and **set the tag's target to the `v1.x` branch** — the UI
defaults to `main`, which is the v2 rework, and a v1 tag created there would
publish the v2 codebase as a stable release. Then ask someone to review the
release.

The package version will be set automatically from the tag.

## v2 Pre-releases

v2 pre-releases are cut from `main` with a PEP 440 pre-release tag: `v2.0.0aN`
for alphas, later `bN`/`rcN` for betas and release candidates.

A release publishes two distributions, `mcp` and `mcp-types`, at the same
version, and the `mcp` wheel exact-pins `mcp-types`. Before the first release
that includes both, the `mcp-types` PyPI project must be given the same
trusted publisher as `mcp` (this repository, workflow `publish-pypi.yml`,
environment `release`) and the same owners — without it the `mcp-types`
upload is rejected. The publish workflow uploads `mcp-types` first so that a
failed upload stops the job before anything `mcp`-named has been published.

1. Check the full test matrix is green on the release commit. The matrix runs
   with `continue-on-error`, so a green workflow run does not mean the tests
   passed — check the individual jobs.
2. Create the release as a pre-release, passing the exact commit verified in
   step 1 as `--target` (otherwise the tag is created from whatever `main`'s
   HEAD is by then). The tagged commit determines everything about the
   release — the workflows that run and the package metadata (readme,
   classifiers) that gets published — so it must contain the current release
   tooling, not just pass tests. `--target` is ignored if the tag already
   exists: when re-creating a release, delete the old tag first and
   double-check where the new tag points. The pre-release flag keeps GitHub's
   "Latest" badge and `/releases/latest` pointing at the stable v1.x line:

   ```shell
   gh release create v2.0.0aN --prerelease --title v2.0.0aN --target <commit-sha>
   ```

3. Curate the release notes instead of relying on auto-generated ones: what
   changed since the previous pre-release, what is known-incomplete, the
   install line (`pip install mcp==2.0.0aN`), and a link to the migration
   guide. Use the absolute URL
   (`https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md`)
   because relative links don't resolve in GitHub release bodies.
4. If a pre-release turns out to be broken, yank it on PyPI and cut the next
   one. Never delete a release from PyPI — version numbers cannot be reused.
   Yanking doesn't stop `==` pins from installing the broken version, so set
   the yank reason (and edit the GitHub release notes) to point at the
   replacement version.
