# Documentation translations

The English pages under `docs/` are the source. This directory holds what steers their machine translation and the generated result; [`docs/translations.md`](../docs/translations.md) is the reader-facing explanation.

- `languages.yml` — the registry: one entry per translated site (served at `/<code>/`), the model id, and the nav pages that stay in English.
- `general-prompt.md` — translation rules shared by every language. `notices.md` — English source of the three notes staged onto the pages of a translated site.
- `<code>/instructions.md` (register, voice, typography, terminology) and `<code>/glossary.json` (`keep`: terms that stay in English; `terms`: required renderings, each with an optional `note` and banned `avoid` renderings, which are checked) — human-authored, sent with every request.
- `<code>/pages/**` and `<code>/notices.md` — **generated**, never edited by hand: a correction goes into that language's `instructions.md` or `glossary.json` (or the English page), and the affected pages are re-run.

## The tool

```text
uv run --frozen python scripts/docs/translations.py status [--lang CODE]
uv run --frozen --group translate python scripts/docs/translations.py translate --lang CODE [--pages PATH ...]
uv run --frozen python scripts/docs/translations.py stage [--lang CODE]
```

`status` is offline: per language it lists missing, outdated (with the sections that changed), current and removable pages (translations whose English page is gone — `git rm` them). `translate` calls the Claude API (`ANTHROPIC_API_KEY` in the environment; the registry's model, or `DOCS_TRANSLATE_MODEL` to trial another) for the missing and outdated pages, retranslating only the English sections that changed and keeping the rest byte for byte; `--pages` instead re-translates exactly the named pages from scratch, which is also how a glossary or instructions change reaches existing pages (each generated page records the English section hashes it reflects, so editing those inputs invalidates nothing). `stage` assembles the tree each language site is built from (every language's, or one with `--lang`): each generated page exactly as it was generated, under an "outdated" notice linking the current English page when the English has changed since, and the English page where nothing was generated yet; `scripts/docs/build.sh` runs it before building them. Commit the generated pages in an ordinary pull request.

To add a language, add an entry to `languages.yml`, write `<code>/instructions.md` (the sections the `pt` file has) and `<code>/glossary.json`, then run `translate --lang <code>`.
