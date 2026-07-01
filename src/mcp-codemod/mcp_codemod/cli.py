"""The `mcp-codemod` command line."""

import argparse
import sys
from collections.abc import Sequence
from difflib import unified_diff
from importlib.metadata import version
from pathlib import Path

from mcp_codemod._dependencies import DependencyReport, update_dependencies
from mcp_codemod._runner import RunReport, discover, run
from mcp_codemod._transformer import MARKER

__all__ = ["main"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-codemod",
        description="Automated rewrites for migrating code between major versions of the MCP Python SDK.",
    )
    parser.add_argument("--version", action="version", version=f"mcp-codemod {version('mcp-codemod')}")
    migrations = parser.add_subparsers(dest="migration", required=True, metavar="MIGRATION")
    v1_to_v2 = migrations.add_parser(
        "v1-to-v2",
        help="rewrite v1 SDK usage to v2 and mark every site that needs a human",
        description=(
            "Rewrite every unambiguous v1 -> v2 change in place and insert a "
            f"`# {MARKER}:` comment above every site that needs a human. "
            "Re-running on the result is a no-op, so it is safe to apply repeatedly."
        ),
    )
    v1_to_v2.add_argument("paths", nargs="+", type=Path, help="files or directories to rewrite")
    v1_to_v2.add_argument("--dry-run", action="store_true", help="report what would change without writing anything")
    v1_to_v2.add_argument("--diff", action="store_true", help="print a unified diff for every changed file")
    v1_to_v2.add_argument("--no-markers", action="store_true", help=f"do not insert `# {MARKER}:` comments")
    return parser


def _print_diffs(report: RunReport) -> None:
    for file in report.files:
        if file.result is None or not file.changed:
            continue
        sys.stdout.writelines(
            unified_diff(
                file.original.splitlines(keepends=True),
                file.result.code.splitlines(keepends=True),
                fromfile=str(file.path),
                tofile=str(file.path),
            )
        )


def _print_summary(
    report: RunReport,
    dependencies: Sequence[DependencyReport],
    *,
    roots: Sequence[Path],
    dry_run: bool,
    markers: bool,
) -> None:
    for file in report.files:
        if file.result is None:
            print(f"{file.path}: failed ({file.error})", file=sys.stderr)
            continue
        if not file.changed and not file.result.diagnostics:
            continue
        rewritten = sum(file.result.rewrites.values())
        attention = sum(1 for diagnostic in file.result.diagnostics if diagnostic.severity != "info")
        print(f"{file.path}: {rewritten} rewritten, {attention} need review")
    for dependency in dependencies:
        if dependency.error is not None:
            print(f"{dependency.path}: failed ({dependency.error})", file=sys.stderr)
        elif dependency.changed:
            flagged = sum(1 for diagnostic in dependency.diagnostics if diagnostic.severity != "info")
            updated = len(dependency.diagnostics) - flagged
            note = "mcp requirement updated for v2" if updated else f"{flagged} need review"
            print(f"{dependency.path}: {note}")

    print(f"\n{len(report.changed)} of {len(report.files)} files rewritten.")
    severities = report.diagnostics
    pending = [
        (dependency.path, diagnostic)
        for dependency in dependencies
        for diagnostic in dependency.diagnostics
        if diagnostic.severity != "info"
    ]
    attention = severities["review"] + severities["manual"] + len(pending)
    if attention:
        if markers and not dry_run:
            targets = " ".join(str(root) for root in roots)
            print(f"{attention} sites still need a human. Find them with:\n  grep -rn '# {MARKER}:' {targets}")
        else:
            # No marker comment landed on disk, so this report is the only record.
            print(f"{attention} sites still need a human:")
            for file in report.files:
                if file.result is None:
                    continue
                for diagnostic in file.result.diagnostics:
                    if diagnostic.severity != "info":
                        print(f"  {file.path}:{diagnostic.line}: {diagnostic.message}")
            for path, diagnostic in pending:
                print(f"  {path}:{diagnostic.line}: {diagnostic.message}")
    if dry_run:
        print("Dry run: nothing was written.")
    failures = len(report.failed) + sum(1 for dependency in dependencies if dependency.error is not None)
    if failures:
        print(f"{failures} files failed.", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the codemod, returning 1 if any file failed and 0 otherwise."""
    args = _build_parser().parse_args(argv)
    report = run(discover(args.paths), write=not args.dry_run, add_markers=not args.no_markers)
    dependencies = update_dependencies(args.paths, write=not args.dry_run, add_markers=not args.no_markers)
    if args.diff:
        _print_diffs(report)
    _print_summary(report, dependencies, roots=args.paths, dry_run=args.dry_run, markers=not args.no_markers)
    failed = report.failed or any(dependency.error is not None for dependency in dependencies)
    return 1 if failed else 0
