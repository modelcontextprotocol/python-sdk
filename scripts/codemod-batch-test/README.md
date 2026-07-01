# Codemod batch test

Runs the `mcp-codemod` v1 -> v2 migration against real, pinned repositories and
audits the result with pyright, to find silent misses the unit tests and the
in-repo example corpus cannot.

## How it works

For each repository in `repos.json`:

1. Clone the pinned commit (shallow).
2. Run the codemod (sources and dependency files) over a copy.
3. Type-check the pristine clone against an environment holding the latest v1
   SDK, and the migrated copy against this workspace's v2 environment, with
   identical pyright settings.
4. Diff the two error sets. Errors only on the migrated side are the migration
   surface; baseline noise (the repo's own issues, missing third-party stubs)
   appears on both sides and cancels out.
5. Correlate each new error with the inserted `# mcp-codemod:` markers.

The codemod's contract is that the markers are the complete list of remaining
manual work, so every new error should sit on or next to a marker. **A new
error with no nearby marker is a silent miss** -- those are printed, written to
`work/results/<slug>.json`, and make the run exit 1.

## Usage

From the repository root (the v1 environment is created on first run):

```bash
uv run --frozen python scripts/codemod-batch-test/run.py            # all repos
uv run --frozen python scripts/codemod-batch-test/run.py --repo mcp-obsidian
uv run --frozen python scripts/codemod-batch-test/run.py --fresh    # re-clone
```

## Adding a repository

Add an entry to `repos.json` with a pinned `sha` (never a branch), an
`include` list when only part of the repository uses the SDK (empty means the
whole tree), and a one-line `note`. Prefer repositories that depend on the
`mcp` package directly; servers built on the external FastMCP library exercise
that library's surface, not this SDK's.
