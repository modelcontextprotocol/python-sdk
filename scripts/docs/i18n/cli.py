"""Command line for the documentation translation tool.

Run from the repository root:

    uv run --frozen --group docs python scripts/docs/i18n <command> [options]

Commands mirror the workflow — `status` shows what each language needs,
`translate` produces or refreshes pages and the sidebar's label map
(`--nav`), `check` and `verify` gate them, `prune` drops translations whose
English source is gone, and `stage` assembles the tree a language site is
built from. Exit codes: 0 success, 1 validation or verification failures,
2 usage or configuration errors.

Commands that call the model (`translate`, `verify`) authenticate from the
environment: set exactly one of ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN
(setting both, or neither, is a configuration error).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import yaml

from i18n.client import AnthropicTranslator, Translator, TranslatorError
from i18n.config import (
    BANNER_KINDS,
    NAV_FILE,
    ROOT,
    ConfigError,
    Language,
    banner_path,
    glossary_path,
    instructions_path,
    load_registry,
    nav_path,
    pages_dir,
    resolve_models,
    state_path,
)
from i18n.files import write_text_atomically
from i18n.glossary import load_glossary
from i18n.nav import save_nav
from i18n.pages import split_blocks, translatable_pages
from i18n.stage import StageStatus, stage_language
from i18n.state import PageState, PageStatus, save_state
from i18n.status import LanguageStatus, language_status
from i18n.translate import (
    Prompt,
    RunContext,
    build_nav_prompt,
    build_prompt,
    semantic_gate,
    translate_nav,
    translate_page,
)
from i18n.validate import Finding, validate_nav_labels, validate_page, validate_page_standalone

EXIT_OK, EXIT_FAILURES, EXIT_USAGE = 0, 1, 2
_STATUSES = ("missing", "outdated", "current", "removable")


class _Environment:
    """The repository the commands operate on."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.docs = root / "docs"
        self.i18n_dir = root / "i18n"
        self.registry = load_registry(self.i18n_dir / "languages.yml")
        self.mkdocs = _mkdocs_config(root / "mkdocs.yml")
        self.nav: list[Any] = self.mkdocs["nav"]

    @property
    def site_url(self) -> str:
        return str(self.mkdocs["site_url"])

    @property
    def site_name(self) -> str:
        return str(self.mkdocs["site_name"])

    def languages(self, code: str | None) -> list[Language]:
        return [self.registry.language(code)] if code else self.registry.enabled

    def status(self, language: Language) -> LanguageStatus:
        return language_status(
            language,
            self.nav,
            self.registry.exclude_pages,
            site_name=self.site_name,
            docs=self.docs,
            i18n_dir=self.i18n_dir,
        )


def _mkdocs_config(path: Path) -> dict[str, Any]:
    """The parsed `mkdocs.yml`: the nav, site name and site URL the commands read.

    Raises:
        ConfigError: The file is missing or unreadable.
    """
    try:
        config: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise ConfigError(f"{path}: not an mkdocs config mapping")
    return cast("dict[str, Any]", config)


def _positive_int(value: str) -> int:
    """An argparse type: a whole number of pages, at least one.

    Raises:
        argparse.ArgumentTypeError: `value` is not an integer of at least one.
    """
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number") from exc
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {number}")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="i18n", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--repo-root", type=Path, default=ROOT, help="Repository root (default: this repository).")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("languages", help="Print the enabled language codes, one per line.")

    status = commands.add_parser(
        "status", help="List missing, outdated, current and removable pages, and the nav map's state."
    )
    status.add_argument("--lang", metavar="CODE", help="Only this language (default: every enabled one).")

    translate = commands.add_parser("translate", help="Translate the selected pages (calls the model).")
    translate.add_argument("--lang", metavar="CODE", required=True)
    translate.add_argument("--pages", nargs="+", metavar="PAGE", default=[], help="Page paths under docs/.")
    translate.add_argument("--nav", action="store_true", help="Translate (or refresh) the sidebar label map.")
    translate.add_argument(
        "--all-missing", action="store_true", help="Add every untranslated page (and the nav map if missing)."
    )
    translate.add_argument(
        "--all-outdated", action="store_true", help="Add every outdated page (and the nav map if outdated)."
    )
    translate.add_argument(
        "--limit", type=_positive_int, metavar="N", help="Translate at most N of the selected pages."
    )
    translate.add_argument("--dry-run", action="store_true", help="Print the assembled prompts; call nothing.")
    translate.add_argument("--no-verify", action="store_true", help="Skip the semantic review gate.")
    translate.add_argument("--model", help="Translation model (overrides languages.yml and the environment).")
    translate.add_argument("--verify-model", help="Semantic-review model (same override rules).")

    check = commands.add_parser(
        "check",
        help="Validate the committed translations and nav label maps: current pages against the English source,"
        " outdated ones on their own (no network).",
    )
    check.add_argument("--lang", metavar="CODE", help="Only this language (default: every enabled one).")
    check.add_argument("--pages", nargs="+", metavar="PAGE", default=[], help="Only these pages.")

    verify = commands.add_parser("verify", help="Run the semantic review gate over pages (calls the model).")
    verify.add_argument("--lang", metavar="CODE", required=True)
    verify.add_argument("--pages", nargs="+", metavar="PAGE", required=True)
    verify.add_argument("--verify-model", help="Semantic-review model (overrides languages.yml and env).")

    prune = commands.add_parser("prune", help="Delete translations whose English page is gone.")
    prune.add_argument("--lang", metavar="CODE", required=True)

    stage = commands.add_parser(
        "stage", help="Assemble a language's staged docs tree for the build under .build/i18n/CODE/docs."
    )
    stage.add_argument("--lang", metavar="CODE", required=True)
    stage.add_argument(
        "--site-url",
        metavar="URL",
        help="Site URL the staged links point at — banner links and API-reference links (default: mkdocs.yml).",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    translator: Translator | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Run one command; returns the process exit code."""
    args = _parser().parse_args(argv)
    environ = os.environ if environ is None else environ
    try:
        env = _Environment(args.repo_root)
        if args.command == "languages":
            print("\n".join(language.code for language in env.registry.enabled))
            return EXIT_OK
        if args.command == "status":
            return _status(env, args)
        if args.command == "translate":
            return _translate(env, args, translator, environ)
        if args.command == "check":
            return _check(env, args)
        if args.command == "verify":
            return _verify(env, args, translator, environ)
        if args.command == "prune":
            return _prune(env, args)
        return _stage(env, args)
    except ConfigError as exc:
        print(f"i18n: {exc}", file=sys.stderr)
        return EXIT_USAGE


def _status(env: _Environment, args: argparse.Namespace) -> int:
    for language in env.languages(args.lang):
        status = env.status(language)
        counts = ", ".join(f"{len(status.select(kind))} {kind}" for kind in _STATUSES)
        print(f"{language.code} ({language.name}): {counts}")
        print(f"  {status.nav_status.status:<9} {NAV_FILE} (navigation labels){_reasons(status.nav_status.reasons)}")
        for page in status.pages:
            print(f"  {page.status:<9} {page.page}{_reasons(page.reasons)}")
    return EXIT_OK


def _reasons(reasons: tuple[str, ...]) -> str:
    return f"  ({'; '.join(reasons)})" if reasons else ""


def _select_pages(status: LanguageStatus, args: argparse.Namespace) -> list[str]:
    """The pages a `translate` run works on, in nav order, deduplicated."""
    listed = {page.page for page in status.pages}
    selected = list(args.pages)
    if unknown := [page for page in selected if page not in listed]:
        raise ConfigError(f"not translatable pages (not in the nav, or excluded): {unknown}")
    if args.all_missing:
        selected += status.select("missing")
    if args.all_outdated:
        selected += status.select("outdated")
    ordered = [page.page for page in status.pages if page.page in set(selected)]
    return ordered if args.limit is None else ordered[: args.limit]


def _select_nav(status: LanguageStatus, args: argparse.Namespace) -> bool:
    """Whether a `translate` run (re)writes the nav map: asked for, or picked up as missing/outdated.

    Raises:
        ConfigError: `--nav` was passed but the nav has no translatable labels.
    """
    if args.nav and not status.labels:
        raise ConfigError("mkdocs.yml has no translatable navigation labels")
    return bool(
        args.nav
        or (args.all_missing and status.nav_status.status == "missing")
        or (args.all_outdated and status.nav_status.status == "outdated")
    )


def _translate(
    env: _Environment, args: argparse.Namespace, translator: Translator | None, environ: Mapping[str, str]
) -> int:
    language = env.registry.language(args.lang)
    status = env.status(language)
    pages = _select_pages(status, args)
    with_nav = _select_nav(status, args)
    if not pages and not with_nav:
        raise ConfigError("nothing selected: pass --pages, --nav, --all-missing or --all-outdated")
    models = resolve_models(env.registry.models, environ=environ, translate=args.model, verify=args.verify_model)
    translations = pages_dir(language.code, env.i18n_dir)

    if args.dry_run:
        if with_nav:
            _print_prompt(
                f"{NAV_FILE} (navigation labels)",
                build_nav_prompt(status.labels, status.inputs, status.nav),
                models.translate,
            )
        for page in pages:
            _print_prompt(
                page, build_prompt(_english(env, page), status.inputs, *_previous(env, status, page)), models.translate
            )
        return EXIT_OK

    if translator is None:
        translator = AnthropicTranslator(environ)
    context = RunContext(
        translator=translator,
        model=models.translate,
        verify_model=models.verify,
        verify=not args.no_verify,
        source_commit=_source_commit(env.root),
        now=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    failed = False
    if with_nav:
        nav_result = translate_nav(status.labels, status.inputs, context, previous=status.nav)
        if nav_result.nav is None:
            failed = True
            print(f"error: {NAV_FILE} failed", file=sys.stderr)
            _print_findings(nav_result.findings)
            if nav_result.error:
                print(f"  {nav_result.error}", file=sys.stderr)
        else:
            save_nav(nav_path(language.code, env.i18n_dir), nav_result.nav)
            print(f"translated: {NAV_FILE} ({len(nav_result.nav.labels)} labels)")
    for page in pages:
        previous, previous_state = _previous(env, status, page)
        result = translate_page(
            page, _english(env, page), status.inputs, context, previous=previous, previous_state=previous_state
        )
        if result.text is None or result.state is None:
            failed = True
            print(f"error: {page} failed", file=sys.stderr)
            _print_findings(result.findings)
            for blocker in result.blockers:
                print(
                    f'  [meaning] "{blocker.source_span}" -> "{blocker.target_span}": {blocker.explanation}',
                    file=sys.stderr,
                )
            if result.error:
                print(f"  {result.error}", file=sys.stderr)
            continue
        write_text_atomically(translations / page, result.text)
        status.state.pages[page] = result.state
        save_state(state_path(language.code, env.i18n_dir), status.state)
        print(f"translated: {page}")
        for drift in result.drifts:
            print(f'  [drift] "{drift.source_span}" -> "{drift.target_span}": {drift.explanation}')
    return EXIT_FAILURES if failed else EXIT_OK


def _print_prompt(subject: str, prompt: Prompt, model: str) -> None:
    """Show one assembled prompt (the `--dry-run` output for a page or the nav map)."""
    print(f"===== {subject} ({prompt.mode}, model {model}) =====")
    print("----- system prompt -----")
    print(prompt.system)
    for message in prompt.messages:
        print(f"----- {message.role} message -----")
        print(message.content)


def _check(env: _Environment, args: argparse.Namespace) -> int:
    """The no-network gate: config, glossaries, nav maps and translated pages are valid.

    Each translated page is checked as what it is. A current page — made
    from the English page and prompt inputs as they stand — is compared with
    the English in full. An outdated page is never measured against the
    English or the glossary that have since moved on (that would fail the
    gate on every English or glossary edit, when staleness only earns a
    banner and a refresh): it only has to be well-formed by itself, and is
    reported so the next translation run refreshes it. A translation whose
    English page is gone, or with no state record, is reported for
    `prune`/`translate` and not read at all. Only real integrity failures
    fail the check.

    A nav map may lag the nav: labels it lacks are not translated yet and
    labels the nav has dropped are stale entries, so neither fails the check
    (`status` reports the map outdated); only the renderings it holds are
    validated. The nav map is skipped when `--pages` narrows the run.
    """
    findings: list[Finding] = []
    for language in env.registry.languages:
        for path in (instructions_path(language.code, env.i18n_dir), glossary_path(language.code, env.i18n_dir)):
            if language.enabled and not path.is_file():
                raise ConfigError(f"{language.code} is enabled but {path} is missing")
        if glossary_path(language.code, env.i18n_dir).is_file():
            load_glossary(glossary_path(language.code, env.i18n_dir))
        for kind in BANNER_KINDS:
            if not banner_path(kind, language.code, env.i18n_dir).is_file():
                raise ConfigError(f"missing banner {kind!r} for {language.code} (and no English fallback)")
    for language in env.languages(args.lang):
        status = env.status(language)
        translations = pages_dir(language.code, env.i18n_dir)
        glossary, script = status.inputs.glossary, language.script
        checked = _checked_pages(language.code, status, translations, args.pages)
        for page in checked:
            name = f"{language.code}:{page.page}"
            output = (translations / page.page).read_text(encoding="utf-8")
            if page.status == "current":
                findings += validate_page(name, _english(env, page.page), output, glossary, script=script)
            elif page.status == "outdated":
                findings += validate_page_standalone(name, output)
        listed = {kind: [p.page for p in checked if p.status == kind] for kind in ("outdated", "removable", "missing")}
        _note(language.code, "outdated", listed["outdated"], "refreshed by the next translation run")
        _note(language.code, "removable", listed["removable"], f"gone from docs/; run `prune --lang {language.code}`")
        _note(
            language.code, "untracked", listed["missing"], "no state.json record; a translation run replaces the file"
        )
        if status.nav is not None and not args.pages:
            findings += validate_nav_labels(
                f"{language.code}:{NAV_FILE}",
                status.labels,
                status.nav.labels,
                status.inputs.glossary,
                exact_keys=False,
            )
            if stale := [label for label in status.nav.labels if label not in set(status.labels)]:
                print(f"note: {language.code}:{NAV_FILE} has stale entries no longer in mkdocs.yml: {stale}")
    _print_findings(findings)
    if findings:
        return EXIT_FAILURES
    print("i18n check: configuration, nav maps and translated pages are valid")
    return EXIT_OK


def _checked_pages(code: str, status: LanguageStatus, translations: Path, selected: Sequence[str]) -> list[PageStatus]:
    """The translated pages `check` looks at: every page with a file, or the `--pages` selection.

    Raises:
        ConfigError: A selected page has no translation file.
    """
    present = [page for page in status.pages if (translations / page.page).is_file()]
    if not selected:
        return present
    by_page = {page.page: page for page in present}
    if missing := [page for page in selected if page not in by_page]:
        raise ConfigError(f"{code} has no translation of {', '.join(missing)}")
    return [by_page[page] for page in selected]


def _note(code: str, kind: str, pages: Sequence[str], remedy: str) -> None:
    """Report pages that need no fix here, only a translation or prune run (never a failure)."""
    if pages:
        count = f"{len(pages)} page" + ("" if len(pages) == 1 else "s")
        print(f"note: {code}: {kind} ({count}) — {remedy}: {', '.join(pages)}")


def _verify(
    env: _Environment, args: argparse.Namespace, translator: Translator | None, environ: Mapping[str, str]
) -> int:
    language = env.registry.language(args.lang)
    status = env.status(language)
    models = resolve_models(env.registry.models, environ=environ, verify=args.verify_model)
    if translator is None:
        translator = AnthropicTranslator(environ)
    failed = False
    for page in args.pages:
        translated = pages_dir(language.code, env.i18n_dir) / page
        if not translated.is_file():
            raise ConfigError(f"{language.code} has no translation of {page}")
        english = _english(env, page)
        output = translated.read_text(encoding="utf-8")
        if findings := validate_page(page, english, output, status.inputs.glossary, script=language.script):
            failed = True
            print(f"error: {page} is not structurally valid (run `check`) — review skipped", file=sys.stderr)
            _print_findings(findings)
            continue
        blocks = list(range(len(split_blocks(english))))
        try:
            blockers, drifts = semantic_gate(english, output, blocks, translator=translator, model=models.verify)
        except TranslatorError as exc:
            failed = True
            print(f"error: {page}: {exc}", file=sys.stderr)
            continue
        for finding in [*blockers, *drifts]:
            stream = sys.stderr if finding.severity == "blocker" else sys.stdout
            quotes = f'"{finding.source_span}" -> "{finding.target_span}"'
            print(f"{page} [{finding.severity}] {quotes}: {finding.explanation}", file=stream)
        failed = failed or bool(blockers)
    print(f"verify: {len(args.pages)} page(s) reviewed with {models.verify}")
    return EXIT_FAILURES if failed else EXIT_OK


def _prune(env: _Environment, args: argparse.Namespace) -> int:
    language = env.registry.language(args.lang)
    status = env.status(language)
    translations = pages_dir(language.code, env.i18n_dir)
    removable = status.select("removable")
    tracked = {page.page for page in status.pages}
    strays = (
        [p.relative_to(translations).as_posix() for p in translations.rglob("*") if p.is_file()]
        if translations.is_dir()
        else []
    )
    for page in sorted(set(removable) | {stray for stray in strays if stray not in tracked}):
        (translations / page).unlink(missing_ok=True)
        status.state.pages.pop(page, None)
        print(f"pruned: {page}")
    save_state(state_path(language.code, env.i18n_dir), status.state)
    return EXIT_OK


def _stage(env: _Environment, args: argparse.Namespace) -> int:
    language = env.registry.language(args.lang)
    status = env.status(language)
    statuses: dict[str, StageStatus] = {}
    for page in status.pages:
        if page.status != "removable":
            statuses[page.page] = page.status
    # Pages excluded from translation are English by design and carry their
    # own note ("available in English only"), distinct from "not translated yet".
    for page in translatable_pages(env.nav, ()):
        statuses.setdefault(page, "excluded")
    site_url = args.site_url or env.site_url
    staged = stage_language(language.code, statuses, english_site_url=site_url, root=env.root)
    for withdrawn in staged.withdrawn:
        links = ", ".join(withdrawn.dead_links)
        print(
            f"warning: {language.code}: {withdrawn.page} not published — its translation links {links},"
            " which the English tree no longer has; staged the English page with the stale banner"
            " (refreshed by the next translation run)",
            file=sys.stderr,
        )
    print(f"staged {language.code} docs at {staged.docs}")
    return EXIT_OK


def _english(env: _Environment, page: str) -> str:
    try:
        return (env.docs / page).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read English page {page}: {exc}") from exc


def _previous(env: _Environment, status: LanguageStatus, page: str) -> tuple[str | None, PageState | None]:
    """The prior translation and its state record, if the page was translated before."""
    record = status.state.pages.get(page)
    translated = pages_dir(status.inputs.language.code, env.i18n_dir) / page
    if record is None or not translated.is_file():
        return None, None
    return translated.read_text(encoding="utf-8"), record


def _print_findings(findings: Sequence[Finding]) -> None:
    for finding in findings:
        print(f"  {finding}", file=sys.stderr)


def _source_commit(root: Path) -> str:
    """The current git commit, recorded so a translation can be traced to its source tree."""
    try:
        completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return completed.stdout.strip()
