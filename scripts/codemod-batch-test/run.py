"""Run the v1 -> v2 codemod against real pinned repositories and audit the result.

For each repository in `repos.json` this script clones the pinned commit, runs
the codemod over a copy, and type-checks both sides with pyright: the pristine
clone against an environment holding the latest v1 SDK, the migrated copy
against this workspace's v2 environment. Errors that appear only on the
migrated side are the migration surface; each one is then correlated with the
`# mcp-codemod:` markers the codemod inserted.

The codemod's headline contract is that the markers are the complete list of
remaining manual work, so every new error should sit on or next to a marker. A
new error with no nearby marker is a silent miss -- the exit code is 1 when any
exists, and each is printed for triage.

Usage, from the repository root:

    uv run --frozen python scripts/codemod-batch-test/run.py [--repo SLUG] [--fresh]
"""

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from mcp_codemod._dependencies import update_dependencies
from mcp_codemod._runner import discover
from mcp_codemod._runner import run as run_codemod
from mcp_codemod._transformer import MARKER

HARNESS_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = HARNESS_DIR.parents[1]
WORK_DIR = HARNESS_DIR / "work"

# The marker-to-error distance (in lines) still counted as "this error is
# explained by that marker". Markers sit on the line above their site; a small
# allowance covers multi-line statements.
MARKER_RADIUS = 3

# Uncovered errors default to actionable. Only these pyright rules, in a file
# the codemod did not touch and with no mcp symbol in the message, are written
# off as v2's own typing getting stricter about the repo's code (mocks no
# longer satisfying defaulted generics, narrower `| None` returns). Notably
# `reportAttributeAccessIssue` is NOT here: a removed attribute the codemod
# failed to flag looks exactly like that.
DRIFT_RULES = frozenset({"reportArgumentType", "reportOptionalSubscript", "reportOptionalMemberAccess"})

# Argument types that detonate at RUNTIME on v2 (`timedelta` where v2 takes float
# seconds, `AnyUrl` where v2 takes `str`). A `reportArgumentType` error naming one
# of these is a real break pyright happens to catch, never strictness drift.
DETONATOR_TYPES = ("timedelta", "AnyUrl")

# The v1 environment lives OUTSIDE the SDK checkout: inside it, uv resolves the
# SDK workspace itself no matter the cwd, and the env would silently hold v2.
V1_ENV_DIR = Path.home() / ".cache" / "mcp-codemod-batch-test" / "v1env"

V1_ENV_PYPROJECT = """\
[project]
name = "codemod-batch-test-v1-env"
version = "0"
requires-python = ">=3.10"
dependencies = ["mcp[cli,ws]>=1.9,<2"]

# Belt and braces: never resolve as a member of some enclosing workspace.
[tool.uv.workspace]
"""


@dataclass(frozen=True, slots=True)
class Repo:
    slug: str
    url: str
    sha: str
    include: tuple[str, ...]
    note: str


@dataclass(frozen=True, slots=True)
class PyrightError:
    file: str
    line: int
    rule: str
    message: str

    @property
    def key(self) -> tuple[str, str, str]:
        """Line-independent identity, so unrelated baseline noise cancels out."""
        return (self.file, self.rule, self.message)


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)


def _load_repos(only: str | None) -> list[Repo]:
    raw: object = json.loads((HARNESS_DIR / "repos.json").read_text())
    assert isinstance(raw, list)
    repos: list[Repo] = []
    for entry in raw:
        assert isinstance(entry, dict)
        repo = Repo(
            slug=str(entry["slug"]),
            url=str(entry["url"]),
            sha=str(entry["sha"]),
            include=tuple(str(item) for item in entry["include"]),
            note=str(entry["note"]),
        )
        if only is None or repo.slug == only:
            repos.append(repo)
    return repos


def _ensure_v1_environment() -> Path:
    """Create (once) an environment holding the latest v1 SDK; return its python.

    The returned interpreter is verified to really import a v1 `mcp.types` --
    a baseline accidentally type-checked against v2 reports no migration delta
    at all, so this fails loudly instead.
    """
    env_dir = V1_ENV_DIR
    python = env_dir / ".venv" / "bin" / "python"
    if not python.is_file():
        env_dir.mkdir(parents=True, exist_ok=True)
        (env_dir / "pyproject.toml").write_text(V1_ENV_PYPROJECT)
        print("setting up the v1 environment (one-time)...")
        sync = _run(["uv", "sync"], cwd=env_dir)
        if sync.returncode != 0:
            sys.exit(f"v1 environment setup failed:\n{sync.stderr}")
    probe = _run([str(python), "-c", "import mcp.types"], cwd=env_dir)
    if probe.returncode != 0:
        sys.exit(f"the v1 environment does not hold a v1 SDK:\n{probe.stderr}")
    return python


def _clone_pinned(repo: Repo, destination: Path, *, fresh: bool) -> None:
    if destination.is_dir():
        if not fresh:
            return
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for command in (
        ["git", "init", "-q"],
        ["git", "remote", "add", "origin", repo.url],
        ["git", "fetch", "-q", "--depth", "1", "origin", repo.sha],
        ["git", "checkout", "-q", "FETCH_HEAD"],
    ):
        result = _run(command, cwd=destination)
        if result.returncode != 0:
            sys.exit(f"{repo.slug}: `{' '.join(command)}` failed:\n{result.stderr}")


def _side_roots(repo: Repo, side: Path) -> list[Path]:
    return [side / sub for sub in repo.include] if repo.include else [side]


def _pyright_errors(repo: Repo, *, python: Path, side: Path) -> list[PyrightError] | None:
    """Type-check one side against the env of `python`, or None when pyright dies.

    The config is written into the side's own root with relative includes, so
    that root is the project root and nothing outside it is ever scanned. The
    interpreter goes on the command line: `--pythonpath` beats the implicit
    `VIRTUAL_ENV` that `uv run` exports, which a config `venvPath` does not.
    """
    config = {
        "include": list(repo.include) or ["."],
        "typeCheckingMode": "basic",
    }
    (side / "pyrightconfig.json").write_text(json.dumps(config))
    result = _run(
        ["uv", "run", "--frozen", "pyright", "--project", str(side), "--pythonpath", str(python), "--outputjson"],
        cwd=WORKSPACE_ROOT,
    )
    try:
        output: object = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"  pyright produced no JSON (exit {result.returncode}):\n{result.stderr}", file=sys.stderr)
        return None
    assert isinstance(output, dict)
    summary = output.get("summary")
    assert isinstance(summary, dict)
    if not summary.get("filesAnalyzed"):
        # A bad include path makes pyright "succeed" over nothing; a verdict
        # based on that would be a lie, so the repo fails instead.
        print(f"  pyright analyzed zero files in {side} -- check the include paths", file=sys.stderr)
        return None
    diagnostics = output.get("generalDiagnostics")
    assert isinstance(diagnostics, list)
    errors: list[PyrightError] = []
    for diagnostic in diagnostics:
        assert isinstance(diagnostic, dict)
        if diagnostic.get("severity") != "error":
            continue
        file = str(Path(str(diagnostic["file"])).relative_to(side))
        start = diagnostic["range"]["start"]["line"]
        assert isinstance(start, int)
        errors.append(
            PyrightError(
                file=file,
                line=start + 1,  # pyright lines are zero-based
                rule=str(diagnostic.get("rule", "")),
                message=str(diagnostic["message"]),
            )
        )
    return errors


def _collect_markers(roots: list[Path], side: Path) -> dict[str, list[int]]:
    """Every `# mcp-codemod:` line in the migrated tree, by file."""
    markers: dict[str, list[int]] = {}
    needle = f"# {MARKER}:"
    for root in roots:
        candidates = [path for path in root.rglob("*") if path.suffix == ".py" or path.name == "pyproject.toml"]
        candidates += list(root.rglob("requirements*.txt"))
        for path in candidates:
            try:
                lines = path.read_bytes().decode("utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            hits = [number for number, line in enumerate(lines, start=1) if needle in line]
            if hits:
                markers[str(path.relative_to(side))] = hits
    return markers


def _audit_repo(repo: Repo, *, v1_python: Path, fresh: bool) -> tuple[dict[str, object], int] | None:
    print(f"\n=== {repo.slug} ({repo.note})")
    pristine = WORK_DIR / "repos" / repo.slug / "pristine"
    migrated = WORK_DIR / "repos" / repo.slug / "migrated"
    _clone_pinned(repo, pristine, fresh=fresh)

    if migrated.is_dir():
        shutil.rmtree(migrated)
    shutil.copytree(pristine, migrated, ignore=shutil.ignore_patterns(".git"))

    roots = _side_roots(repo, migrated)
    report = run_codemod(discover(roots), write=True)
    dependency_reports = update_dependencies(roots, write=True)
    severities = report.diagnostics
    rewritten_files = {str(file.path.relative_to(migrated)) for file in report.changed}
    print(
        f"  codemod: {len(report.changed)} of {len(report.files)} files rewritten, "
        f"{severities['manual'] + severities['review']} flagged sites, "
        f"{sum(1 for dependency in dependency_reports if dependency.changed)} dependency files updated"
    )

    baseline = _pyright_errors(repo, python=v1_python, side=pristine)
    post = _pyright_errors(repo, python=WORKSPACE_ROOT / ".venv" / "bin" / "python", side=migrated)
    if baseline is None or post is None:
        return None
    baseline_keys = {error.key for error in baseline}
    new_errors = [error for error in post if error.key not in baseline_keys]
    resolved = len(baseline) - len([error for error in baseline if error.key in {e.key for e in post}])

    markers = _collect_markers(roots, migrated)
    actionable: list[PyrightError] = []
    drift: list[PyrightError] = []
    for error in new_errors:
        nearby = markers.get(error.file, [])
        if any(abs(line - error.line) <= MARKER_RADIUS for line in nearby):
            continue
        # Uncovered errors are actionable unless everything says v2 strictness
        # drift: an untouched file, no mcp symbol in the message, and a rule
        # from the drift list. A silent codemod miss fails any one of these.
        if (
            error.file not in rewritten_files
            and "mcp" not in error.message.lower()
            and error.rule in DRIFT_RULES
            and not any(f'of type "{detonator}"' in error.message for detonator in DETONATOR_TYPES)
        ):
            drift.append(error)
        else:
            actionable.append(error)

    covered = len(new_errors) - len(actionable) - len(drift)
    print(
        f"  pyright: {len(baseline)} baseline errors, {len(new_errors)} new after migration "
        f"({resolved} resolved): {covered} covered by markers, {len(drift)} v2 strictness drift"
    )
    for error in actionable:
        print(f"  UNCOVERED  {error.file}:{error.line}  [{error.rule}] {error.message.splitlines()[0]}")

    result: dict[str, object] = {
        "slug": repo.slug,
        "sha": repo.sha,
        "files_rewritten": len(report.changed),
        "files_total": len(report.files),
        "flagged_sites": severities["manual"] + severities["review"],
        "baseline_errors": len(baseline),
        "new_errors": len(new_errors),
        "covered_by_markers": covered,
        "strictness_drift": [
            {"file": error.file, "line": error.line, "rule": error.rule, "message": error.message} for error in drift
        ],
        "uncovered": [
            {"file": error.file, "line": error.line, "rule": error.rule, "message": error.message}
            for error in actionable
        ],
    }
    return result, len(actionable)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="run a single repository by slug")
    parser.add_argument("--fresh", action="store_true", help="re-clone repositories even when present")
    args = parser.parse_args()

    repos = _load_repos(args.repo)
    if not repos:
        sys.exit(f"no repository matches {args.repo!r}")
    WORK_DIR.mkdir(exist_ok=True)
    v1_python = _ensure_v1_environment()

    results: list[dict[str, object]] = []
    total_uncovered = 0
    for repo in repos:
        audited = _audit_repo(repo, v1_python=v1_python, fresh=args.fresh)
        if audited is not None:
            result, uncovered = audited
            results.append(result)
            total_uncovered += uncovered

    results_dir = WORK_DIR / "results"
    results_dir.mkdir(exist_ok=True)
    for result in results:
        (results_dir / f"{result['slug']}.json").write_text(json.dumps(result, indent=2) + "\n")

    print(f"\n{len(results)} repositories audited; {total_uncovered} uncovered new errors.")
    return 1 if total_uncovered or len(results) != len(repos) else 0


if __name__ == "__main__":
    sys.exit(main())
