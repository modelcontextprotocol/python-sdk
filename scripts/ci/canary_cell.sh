#!/usr/bin/env bash
# One dependency-canary test cell: install the resolved lock, run the suite,
# and classify the outcome so the report can tell a hard break from a new
# deprecation warning or a flake. Driven by .github/workflows/dependency-canary.yml.
#
# Inputs (env): CANARY_CELL (label, e.g. "ubuntu-3.14"), CANARY_PYTHON (e.g. "3.14"),
#               CANARY_PYRIGHT=1 to append an informational `pyright src/mcp` result.
# Outputs: canary-out/status  — one of: pass | flaky | warnings-only | error | install-failed
#          canary-out/cell.md  — Markdown section for the issue body / job summary
# Exit status: 0 for pass/flaky, 1 otherwise (so the job shows red).

set -uo pipefail

cell="${CANARY_CELL:?}"
python="${CANARY_PYTHON:?}"
out=canary-out
mkdir -p "$out"
md="$out/cell.md"
status=pass
export COLUMNS=200 # keeps pytest from truncating the -r summary lines quoted in the report

pytest_cmd=(uv run --frozen --no-sync pytest -p no:pretty -q --no-header -rfE --color=no -o log_cli=false)
# Demote only the deprecation family: if failures vanish under these, the newest
# versions still work and merely announce a future removal.
demote=(-W default::DeprecationWarning -W default::PendingDeprecationWarning -W default::FutureWarning)

summary_of() { # print the short-summary FAILED/ERROR lines of a pytest log, capped
  grep -E '^(FAILED|ERROR) ' "$1" | head -n 40
  local n
  n=$(grep -cE '^(FAILED|ERROR) ' "$1")
  if [ "$n" -gt 40 ]; then echo "... and $((n - 40)) more"; fi
}

details_of() { # collapsed tail of a log
  printf '<details><summary>%s</summary>\n\n```text\n' "$2"
  tail -n "${3:-60}" "$1" | sed 's/```/` ` `/g'
  printf '```\n\n</details>\n'
}

{
  echo "#### $cell"
  echo
} >"$md"

if ! uv sync --frozen --all-extras --python "$python" >"$out/sync.log" 2>&1; then
  status=install-failed
  {
    echo "**Install failed** — \`uv sync --frozen --all-extras --python $python\` could not install the resolved set on this platform."
    echo
    details_of "$out/sync.log" "uv sync output" 40
  } >>"$md"
else
  installed=$(uv run --frozen --no-sync python -V 2>/dev/null)
  if "${pytest_cmd[@]}" -n auto >"$out/run1.log" 2>&1; then
    echo "All tests pass ($installed)." >>"$md"
  else
    rc=$?
    if [ "$rc" -eq 1 ]; then
      # Ordinary test failures: re-run just those, serially, to drop xdist/ordering flakes.
      rerun=("${pytest_cmd[@]}" --lf --last-failed-no-failures none -p no:xdist)
    else
      # Collection/usage/internal error (e.g. a warning raised at import time): no
      # last-failed set to narrow to, so re-run everything.
      rerun=("${pytest_cmd[@]}" -n auto)
    fi
    if [ "$rc" -eq 1 ] && "${rerun[@]}" >"$out/run2.log" 2>&1; then
      status=flaky
      {
        echo "Passed on a serial re-run ($installed); first attempt had failures (treated as flaky, not reported):"
        echo
        echo '```text'
        summary_of "$out/run1.log"
        echo '```'
      } >>"$md"
    else
      [ -f "$out/run2.log" ] || cp "$out/run1.log" "$out/run2.log"
      if "${rerun[@]}" "${demote[@]}" >"$out/run3.log" 2>&1; then
        status=warnings-only
        {
          echo "**Deprecation warnings only** ($installed) — the failures below disappear when"
          echo "\`DeprecationWarning\`/\`PendingDeprecationWarning\`/\`FutureWarning\` are not errors, so newest versions still work but announce a removal we need to get ahead of."
        } >>"$md"
      else
        status=error
        echo "**Hard failures** ($installed) — these persist on a serial re-run and with deprecation warnings demoted:" >>"$md"
      fi
      {
        echo
        echo '```text'
        summary_of "$out/run2.log"
        echo '```'
        echo
        details_of "$out/run2.log" "pytest output (tail)" 80
      } >>"$md"
    fi
  fi

  if [ "${CANARY_PYRIGHT:-}" = "1" ]; then
    if uv run --frozen --no-sync pyright src/mcp >"$out/pyright.log" 2>&1; then
      printf '\npyright on `src/mcp` against these versions: clean (informational).\n' >>"$md"
    else
      {
        echo
        details_of "$out/pyright.log" "pyright on <code>src/mcp</code> against these versions: $(tail -n1 "$out/pyright.log") (informational, never filed on its own)" 30
      } >>"$md"
    fi
  fi
fi

echo "$status" >"$out/status"
echo "canary cell $cell: $status"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then cat "$md" >>"$GITHUB_STEP_SUMMARY"; fi
case "$status" in pass | flaky) exit 0 ;; *) exit 1 ;; esac
