"""Machine translation of the documentation into the language sites.

The English pages under `docs/` are the source; each language listed in
`i18n/languages.yml` gets generated translations under
`i18n/languages/<code>/pages/`, steered by that language's `instructions.md`
and `glossary.json`. `i18n/README.md` documents the workflow; run the tool as
`python scripts/docs/i18n --help` from the repo root for the commands.
"""
