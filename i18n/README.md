# Documentation translations

The English pages under `docs/` are the source of truth. This directory holds
what steers their machine translation (human-authored) and the generated
result; the public-facing explanation is [`docs/translations.md`](../docs/translations.md).

- `languages.yml` — the language registry (one entry per translated site,
  served at `/<code>/`), the pages that stay English, the model IDs, and the
  English text of the notices staged onto every translated page.
- `general-prompt.md` — the translation rules shared by every language.
- `<code>/instructions.md` — register, voice, humour and typography for one
  language. Human-authored.
- `<code>/glossary.json` — the termbase for one language: terms that stay in
  English, required renderings, and banned ones (`"enforce": true` makes a ban
  a hard check). Human-authored.
- `<code>/pages/` and `<code>/state.json` — generated: the translated pages and
  the record of what each was made from (English content and section hashes, prompt
  inputs, model, timestamp), plus the translated sidebar labels and notices. Never
  edited by hand.

## The tool

`scripts/docs/translations.py` (run from the repository root):

```bash
uv run --frozen --group docs python scripts/docs/translations.py status           # missing/outdated/current per language
uv run --frozen --group docs python scripts/docs/translations.py translate --lang ja # translate what is missing or outdated
uv run --frozen --group docs python scripts/docs/translations.py stage --lang ja     # the docs tree the ja site builds from
```

`translate` calls the Claude API (set `ANTHROPIC_API_KEY` or
`ANTHROPIC_AUTH_TOKEN`). It re-translates only the `##` sections whose English
changed and carries the rest of the page over byte-for-byte from the previous
translation, then gates the result: heading anchors and code blocks are
re-imposed from the English, the page's structure (headings, code fences,
links, admonitions, glossary rules) is checked with the findings fed back for
another attempt, and a stronger model reviews the meaning against the English.
`--pages a.md b.md` narrows a run (a page that is already current comes back
unchanged), `--fresh` re-translates from scratch instead of updating (every
page when no `--pages` are given — the way to redo a language after a model
change), `--dry-run` shows what it would do, and `--no-verify` skips the
meaning review. A page that failed its gates keeps its previous translation and
the run exits non-zero; translations whose English page has left the nav are
deleted. Everything else is offline; `scripts/docs/build.sh` runs `stage` for
each language and builds it at `site/<code>/`.

## Correcting a translation

Never edit a file under `<code>/pages/` — the next run overwrites it. Fix the
input instead: a wrong term goes into `glossary.json`, a recurring style or
register problem into `instructions.md`, and ambiguous English into the page
under `docs/`. Editing a glossary or instructions marks that language's pages
outdated, so the next `translate` run regenerates them with the fix in place.
Readers report problems through the "Translation problem" issue form.

## Staleness

A page is *current* when the English content and the prompt inputs it was
translated from are unchanged, *outdated* otherwise, and *missing* when it has
no translation. The build serves an outdated translation with a warning
notice, unless the English page's links or heading anchors moved under it —
then the English page is served until the next `translate` run refreshes it.
Untranslated and excluded pages are served in English with a notice.

## Adding a language

Add an entry to `languages.yml` (`code`, native `name`; `theme_language` and
`hreflang` default to the code and must be values the theme knows), write
`<code>/instructions.md` and `<code>/glossary.json` (start from an existing
language), then run `translate --lang <code>` and commit the generated `pages/`
and `state.json`. Also name the language in `docs/translations.md` and the
"Translation problem" issue form's dropdown.
