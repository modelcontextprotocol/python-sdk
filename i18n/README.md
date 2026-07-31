# Documentation translations

The English documentation under `docs/` is the source of truth. Everything in this directory either steers how those pages are machine-translated (human-authored inputs) or is the generated output of that process. The public-facing explanation lives at [`docs/translations.md`](../docs/translations.md); this file is for maintainers.

## Layout

- `languages.yml` — the language registry: one entry per language site (directory/URL code, native name, theme language, hreflang, enabled flag), the pages excluded from translation, and the model IDs the tool uses. The build and the tool both read it; nothing else hardcodes the language list.
- `general-prompt.md` — the translation rules shared by every language. Sent with every translation request.
- `banners/<code>/` — the notes staged onto pages in each language site: `disclosure.md` (machine-translated notice), `outdated.md` (may be behind the English page), `untranslated.md` (not translated yet), `stale.md` (translation withdrawn while it is refreshed — see below) and `english-only.md` (page deliberately kept in English). The build fills the `{english_url}` and `{translations_page_url}` placeholders; `banners/en/` is the fallback used when a language has no translated banner text.
- `languages/<code>/instructions.md` — register, voice, humour policy and typography for one language. Human-authored.
- `languages/<code>/glossary.json` — the termbase for one language: terms that stay in English, required renderings, and banned renderings. Human-authored, validated by the tool.
- `languages/<code>/pages/` — the generated translations, mirroring the paths under `docs/`. Never edited by hand (see below).
- `languages/<code>/state.json` — the generated record of what each translated page was built from.
- `languages/<code>/nav.yml` — the generated map from each English sidebar label in `mkdocs.yml` (section titles and explicit `Label: page.md` entries) to its translation, plus the record of what it was built from. The language build swaps these into the sidebar; a label without a rendering stays English. Never edited by hand.

## The tool

Translation, validation and housekeeping are handled by the package under `scripts/docs/i18n/`, which provides these commands:

```bash
uv run --frozen --group docs python scripts/docs/i18n <command> [options]
```

- `status [--lang <code>]` — for each enabled language, list pages that are missing, outdated (English changed since translation, or prompt/glossary fingerprint changed), current, and removable (English page deleted), plus the state of its `nav.yml` label map. No network.
- `translate --lang <code> [--pages a.md b.md] [--nav] [--all-missing] [--all-outdated] [--limit N] [--dry-run] [--no-verify]` — translate the selected pages (network), and with `--nav` (re)generate the language's `nav.yml` label map; `--all-missing`/`--all-outdated` also pick the map up when it is missing or outdated. Nothing is selected unless you pass `--pages`, `--nav` or an `--all-*` flag. `--limit` caps pages only. `--dry-run` prints the assembled prompts (the nav prompt included) and exits without calling the API.
- `check [--lang <code>] [--pages ...]` — validate the committed translations and each language's `nav.yml`, no network; this is the CI gate for pull requests touching `i18n/`, and it only ever fails for a real integrity problem. Each page is checked as what it is: a *current* page (English source, glossary and instructions unchanged) gets the full structural validation against that English page; an *outdated* page is not measured against the English or the glossary that have since moved on — it only has to be well-formed by itself (front matter closes, every code fence closes, headings pin distinct well-formed anchors) and is reported so the next translation run refreshes it. Glossary rules are deliberately not enforced on an outdated page: a glossary edit is one of the things that makes a page outdated, and enforcing it offline would fail the gate until a fresh translation run landed. A page whose English source is gone is reported for `prune`, and a translation file with no `state.json` record is reported as untracked. For a `nav.yml` map, labels it lacks are merely behind and entries for labels the nav has dropped are reported as stale, neither failing the check (`--pages` narrows the run to pages only). English and glossary edits therefore never fail `check`; staleness is bannered by the build, not blocked here.
- `verify --lang <code> --pages ...` — run the semantic review gate over the given pages (network). `translate` runs it on freshly generated text unless `--no-verify` is passed.
- `prune --lang <code>` — delete translated pages whose English source no longer exists and drop them from the state file.
- `stage --lang <code> [--site-url URL]` and `languages` — build machinery used by `scripts/docs/build.sh`: `stage` assembles a language's docs tree under `.build/i18n/<code>/docs/` (English pages, translations laid over them, status banners stamped in, and links into the API reference pointed at the English one — a language site links to the single English API reference rather than building its own), and `languages` prints the enabled codes. `--site-url` names the URL the site is served from (the build script derives it from `DOCS_SITE_URL`, defaulting to `mkdocs.yml`'s `site_url`), which the banners' English-page links and the API-reference links are built on. A translation whose links no longer resolve against the English tree (its English page has since renamed or dropped a target the translation still links) is withdrawn rather than staged — the English page is served with the `stale` banner and `stage` prints a warning line for it — so an outdated translation can delay a language site but never break its build.

Exit codes: `0` success, `1` validation or verification failures, `2` usage or configuration errors. The network commands read `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`) from the environment and fail fast if neither is set; the model IDs come from `languages.yml` and can be overridden with `MCP_DOCS_I18N_MODEL` and `MCP_DOCS_I18N_VERIFY_MODEL`. Run any command with `--help` for the full option list.

## Correcting a translation

Never edit the files under `languages/<code>/pages/` or a language's `nav.yml` — the next translation run overwrites them. Put the correction where the tool will pick it up:

- A wrong or inconsistent term → add or fix an entry in that language's `glossary.json`.
- A recurring style or register problem (too formal, a joke that lands badly, an awkward loanword) → add a rule to that language's `instructions.md`, ideally with a short good/bad example.
- English text that is ambiguous or hard to translate → fix the English page under `docs/`.

Editing the instructions or glossary changes their fingerprint, which marks that language's pages and nav map as outdated (see below), so the next `translate --all-outdated` run regenerates them with the fix in place. A wrong sidebar label is corrected the same way — through the glossary or instructions, then a `--nav` (or `--all-outdated`) run.

Readers report problems through the "Translation problem" issue form (`.github/ISSUE_TEMPLATE/translation.yaml`), which applies the `translation` label; triage each report into one of the three fixes above.

## How staleness works

`languages/<code>/state.json` records, for every translated page, the git commit and content hash of the English page it was translated from, a hash per content block, the fingerprints of `general-prompt.md`, that language's `instructions.md` and `glossary.json`, and the model and timestamp of the run. A page is a set of blocks: its front matter, the text before the first `##` heading, then one block per `##` section, so an edit to one section only re-translates that section and the untouched blocks are carried over verbatim from the previous translation.

`status` compares those records against the current English tree: a page is *missing* if it has no translation, *outdated* if any recorded hash or fingerprint no longer matches, *current* otherwise, and *removable* if its English source is gone. The docs build reads the same state to add a "may be behind the English page" note to outdated pages; pages with no translation are served from the English source with a "not translated yet" note. An outdated page whose translation still links a page the English tree has since renamed or removed is a special case: it would break the language site's strict build, so `status` reports it as "links broken by an English change — English shown until refreshed" and the build serves the English page with the `stale` banner until the next translation run rewrites it. Its `state.json` record already marks it outdated, so nothing else is needed — the next `translate --all-outdated` run refreshes it like any other outdated page.

The nav map follows the same contract at a smaller grain. `languages/<code>/nav.yml` records a hash of the ordered English label list plus the same three prompt-input fingerprints, so it is *missing* until first generated, *outdated* when a label is added, removed or reworded in `mkdocs.yml` or when the general prompt, instructions or glossary change, and *current* otherwise. A retranslation carries every label whose prompt inputs are unchanged over from the previous map byte-for-byte, so only new labels come from the model; a glossary or instructions edit re-asks the whole list. A label with no rendering is shown in English rather than failing the build.

## Adding a language

1. Add an entry to `languages.yml` (code, native name, theme language, hreflang, `enabled: true`).
2. Create `languages/<code>/instructions.md` with these sections in this order: register, voice, humour and idioms, typography, terminology, and a provisional note. Keep it tight; it is sent verbatim with every request.
3. Create `languages/<code>/glossary.json`: the `keep_in_source_language` list plus the seed `terms` entries.
4. Optionally add `banners/<code>/` with translated banner text; without it the English banners are used.
5. Run `status --lang <code>` to see what is missing, then `translate --lang <code> --all-missing`. The `pages/` tree, `state.json` and `nav.yml` are generated by that run; commit them.
