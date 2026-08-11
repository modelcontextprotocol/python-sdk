# Documentation translations

The English pages under `docs/` are the source. This directory holds what steers their machine translation and the generated result; [`docs/translations.md`](../docs/translations.md) is the reader-facing explanation.

- `languages.yml` — the registry: one entry per translated site (served at `/<code>/`), the model id, and the nav pages that stay in English.
- `general-prompt.md` — translation rules shared by every language. `notices.md` — English source of the three notes staged onto the pages of a translated site.
- `<code>/instructions.md` (register, voice, humour, typography, terminology) and `<code>/glossary.json` (`keep`: terms that stay in English; `terms`: required renderings, each with an optional `note` and banned `avoid` renderings, which are checked) — human-authored, sent with every request.
- `<code>/pages/**` and `<code>/notices.md` — **generated**, never edited by hand: the next run overwrites them. A correction goes into that language's `instructions.md` or `glossary.json` (or into the English page), and the affected pages are then re-run.

## The tool

```text
uv run --frozen python scripts/docs/translations.py status [--lang CODE]
uv run --frozen --group translate python scripts/docs/translations.py translate --lang CODE
        [--pages PATH ... | --grep REGEX] [--limit N] [--dry-run]
uv run --frozen python scripts/docs/translations.py stage --lang CODE
```

`status` is offline: per language it lists missing, outdated (with the sections that changed), current and removable pages (translations whose English page is gone — `git rm` them), and pages the build will serve in English. `translate` calls the Claude API (`ANTHROPIC_API_KEY` in the environment) for missing and outdated pages, at most `--limit` (default 15) per run; `--pages` re-translates exactly the named pages from scratch (English only, no previous translation shown), `--grep` selects current pages whose English matches and reopens only the matching sections, and `--dry-run` prints the assembled prompts without calling anything. The model is the registry's, or `DOCS_TRANSLATE_MODEL` from the environment to trial another one for a run without editing the registry. `stage` assembles the tree a language site is built from; `scripts/docs/build.sh` runs it for every language.

A page is outdated only when an English section it was translated from has changed; each generated page records the section hashes it reflects (plus a fingerprint of its prompt inputs, for information) in front matter that the build strips. Editing a glossary or instructions file therefore invalidates nothing: apply such a change to existing pages with `translate --grep`, which revises only the matching sections and keeps the rest byte-for-byte, or with `--pages` for a fresh translation of whole pages.

## Adding a language

Add an entry to `languages.yml`, write `<code>/instructions.md` (the six sections the pt-BR file has) and `<code>/glossary.json`, then dispatch the `.github/workflows/translate.yml` workflow for that code: it translates, builds the site strictly, and opens a draft pull request on branch `translate/<code>` with the generated pages, requesting the reviewers named in the registry. Each dispatch starts from `main`, so either pass a `limit` at least the page count `status` reports to fill a language in one run, or merge each refresh pull request before dispatching the next (a second run before the merge redoes the same pages). The workflow needs an `ANTHROPIC_API_KEY` repository secret, and the repository needs a `translation` label, which the issue form and the workflow's pull requests carry.
