# Release Process

## Bumping Dependencies

[`DEPENDENCY_POLICY.md`](DEPENDENCY_POLICY.md) says *when* a bound should
move; this is the mechanics.

1. Change the dependency version in `pyproject.toml`. The root `mcp` project's
   runtime dependencies are dynamic and live under
   `[tool.hatch.metadata.hooks.uv-dynamic-versioning].dependencies`.
2. Regenerate the lock with `uv lock` (or `uv lock --upgrade-package <package>`
   to move just that package's locked version). The committed `uv.lock` is a
   normal (default-strategy) resolution; the `lowest-direct` resolution that
   proves the floors still work is applied only by its CI matrix leg at test
   time and is never committed.

## Release lines

Two branches ship, and the package version comes from the git tag
(`uv-dynamic-versioning`). Publishing a GitHub release runs `publish-pypi.yml`
**from the tagged commit**, so the workflow that fires is the tagged branch's
own: a `main` tag builds and publishes two distributions (`mcp` and
`mcp-types`, lock-stepped via `Requires-Dist: mcp-types=={{ version }}`), and a
`v1.x` tag builds and publishes `mcp` only.

| Line                         | Branch | Tag                       | GitHub release flags                  |
| ---------------------------- | ------ | ------------------------- | ------------------------------------- |
| Current stable               | `main` | `v2.X.Y`                  | not a pre-release; becomes **Latest** |
| Maintenance (previous major) | `v1.x` | `v1.X.Y`                  | not a pre-release; **not** Latest     |
| Pre-releases                 | `main` | `v2.X.YaN` / `bN` / `rcN` | **Pre-release** ticked, never Latest  |

The `Development Status` classifier in both `pyproject.toml` files is
permanently `5 - Production/Stable`; it is not bumped as part of any release.
The `mcp-types` PyPI project carries the same trusted publisher as `mcp` (this
repository, workflow `publish-pypi.yml`, environment `release`). For a release
cut from `main`, if only some of the four files upload, fix the cause and
re-run the publish job — its `skip-existing` setting makes it skip whatever
already landed (the `v1.x` workflow publishes a single distribution and has no
such setting).

## Stable release from `main` (`v2.X.Y`)

The stable line's README and docs carry no version pin (`pip install "mcp[cli]"`
installs the newest stable release), so a routine stable release needs no
pin-flip commit; the exception is the first stable release of a new major,
whose pre-release banner and pins are replaced by that flip. `README.md` at the
tagged commit is the PyPI long description, so any README fix has to merge
before the tag.

1. Check the full test matrix is green on the release commit. The publish
   workflow re-runs the same checks and blocks publishing until they pass, so a
   red leg there means re-running the failed jobs on the Publishing run — but
   verify green before creating the release rather than discovering red after
   the tag exists.
2. Freeze `main` from that commit until the tag exists: the release is created
   with an explicit `--target`, and nothing else should land in between.
3. Create the release NOT as a pre-release, passing the verified commit as
   `--target` (otherwise the tag is created from whatever `main`'s HEAD is by
   then). It becomes GitHub "Latest", and PyPI's default `pip install mcp`
   version moves to it. The tagged commit determines everything about the
   release — the workflows that run and the package metadata (readme,
   classifiers) that gets published — so it must contain the current release
   tooling, not just pass tests. `--target` is ignored if the tag already
   exists: when re-creating a release, delete the old tag first and
   double-check where the new tag points.

   ```shell
   gh release create v2.X.Y --title v2.X.Y --target <commit-sha> --notes-file <notes.md>
   ```

4. Curate the release notes: the highlights, anything known-incomplete, and
   links to the docs and migration guide, above a `## What's Changed` list.
   Generate that list with the release UI's "Generate release notes" (setting
   its **Previous tag** to the previous release on this line by hand — the
   auto-picked baseline is the newest tag, which may sit on the other line), or
   assemble the whole body in the file passed to `--notes-file`. Use absolute
   URLs (relative links don't resolve in GitHub release bodies).
5. If a stable release turns out to be broken, yank it on PyPI and release the
   fix as the next patch version. Never delete a release from PyPI — version
   numbers cannot be reused. Yank `mcp` and `mcp-types` together (they are one
   release), and set the yank reason and the GitHub release notes to point at
   the replacement version, since yanking doesn't stop `==` pins from installing
   the broken version.

## Maintenance release from `v1.x` (`v1.X.Y`)

Land the `[v1.x]`-prefixed backport PRs (and any README banner update, which is
the README PyPI shows for that version), verify the branch tip green, then
create the release the same way with two differences:

- **The tag's target is the verified commit on the `v1.x` branch.** The UI and
  CLI default the target to `main`, which is the v2 codebase — a v1 tag created
  there would publish v2 code as a v1 stable release. Pass the exact commit
  verified green in the previous step rather than the branch name, for the
  same moving-HEAD reason as above.
- **It must not take "Latest" back from the 2.x line.** The UI ticks "Set as
  the latest release" by default for the newest non-pre-release; untick it, or
  pass `--latest=false`, and afterwards confirm `/releases/latest` still names
  the newest v2 tag. If it slipped, `gh release edit v1.X.Y --latest=false`
  fixes it — release metadata only, no re-cut.

```shell
gh release create v1.X.Y --title v1.X.Y --target <commit-sha> --latest=false --notes-file <notes.md>
```

When generating notes, set **Previous tag** to the previous `v1.*` release by
hand for the same reason as above. Then ask someone to review the release.

## Pre-releases from `main`

Pre-releases of the next version are cut from `main` with a PEP 440
pre-release tag: `aN` for alphas, later `bN`/`rcN` for betas and release
candidates. The PEP 440 suffix is what keeps `pip install mcp` on the stable
version — installers do not pick a pre-release for a plain `mcp` requirement while a
final release satisfies it; a pre-release is opted into with an exact pin, a
specifier that names a pre-release version, or `--pre`.

1. During a pre-release phase the README and docs pin the exact pre-release
   version, so update those examples first (grep the outgoing version — the
   pins live in the README Installation section, `docs/index.md`,
   `docs/get-started/installation.md`, and `docs/get-started/real-host.md`) so
   the tagged commit — and therefore the README PyPI publishes — names the
   version being released. When entering a new phase (alpha → beta → rc →
   stable), update the banner wording too; the stable phase drops the pins.
2. Check the full test matrix is green on the release commit, as above.
3. Create the release as a pre-release, passing the verified commit as
   `--target`. The pre-release flag keeps GitHub's "Latest" badge and
   `/releases/latest` on the newest stable release:

   ```shell
   gh release create v2.X.YbN --prerelease --title v2.X.YbN --target <commit-sha>
   ```

4. Curate the release notes: what changed since the previous pre-release, what
   is known-incomplete, the install line (`pip install mcp==2.X.YbN`), and a
   link to the migration guide, with absolute URLs.
5. If a pre-release turns out to be broken, yank both `mcp` and `mcp-types` on PyPI
   and cut the next one, pointing the yank reason and the GitHub release notes
   at the replacement version.
