#!/usr/bin/env bash
# One dependency-canary test cell: install the resolved lock, run the suite,
# and classify the outcome so the report can tell a hard break from a new
# deprecation warning or a flake. Driven by .github/workflows/dependency-canary.yml.
#
# Inputs (env): CANARY_CELL (label, e.g. "ubuntu-3.14"), CANARY_PYTHON (e.g. "3.14"),
#               CANARY_PYRIGHT=1 to append an informational `pyright src/mcp` result.
# Outputs under out/canary-cell-$CANARY_CELL/:
#   status   — pass | flaky | warnings-only | error | install-failed
#              ("incomplete" is written first, so a killed cell still says something)
#   cell.md  — Markdown section for the issue body / job summary (bounded to ~20 kB)
#   *.log    — raw logs, kept in the artifact for debugging
# Exit status: 0 for pass/flaky, 1 otherwise (so the job shows red).

set -uo pipefail

cell="${CANARY_CELL:?}"
python="${CANARY_PYTHON:?}"
out="out/canary-cell-$cell"
mkdir -p "$out"
md="$out/cell.md"
echo incomplete >"$out/status"
printf '#### %s\n\nDid not finish (see the workflow run).\n' "$cell" >"$md"
export COLUMNS=200 # keeps pytest from truncating the -r summary lines quoted in the report

pytest_cmd=(uv run --frozen --no-sync pytest -p no:pretty -q --no-header -rfE --color=no -o log_cli=false)
# Demote only the deprecation family: if failures vanish under these, the newest
# versions still work and merely announce a future removal.
demote=(-W default::DeprecationWarning -W default::PendingDeprecationWarning -W default::FutureWarning)

summary_of() { # the short-summary FAILED/ERROR lines of a pytest log, capped; falls back to the log tail
  local lines
  lines=$(grep -E '^(FAILED|ERROR) ' "$1" | awk '!seen[$0]++' | cut -c1-240) # xdist repeats collection errors per worker
  if [ -z "$lines" ]; then
    tail -n 15 "$1" | cut -c1-240
    return
  fi
  head -n 40 <<<"$lines"
  local n
  n=$(wc -l <<<"$lines")
  if [ "$n" -gt 40 ]; then echo "... and $((n - 40)) more"; fi
}

details_of() { # collapsed, size-bounded tail of a log: file, summary text, max lines
  printf '<details><summary>%s</summary>\n\n```text\n' "$2"
  tail -n "${3:-60}" "$1" | cut -c1-240 | head -c 12000 | sed 's/```/` ` `/g'
  printf '\n```\n\n</details>\n'
}

finish() {
  echo "$1" >"$out/status"
  echo "canary cell $cell: $1"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then cat "$md" >>"$GITHUB_STEP_SUMMARY"; fi
  case "$1" in pass | flaky) exit 0 ;; *) exit 1 ;; esac
}

printf '#### %s\n\n' "$cell" >"$md"

if ! uv sync --frozen --all-extras --python "$python" >"$out/sync.log" 2>&1; then
  {
    echo "**Install failed** — \`uv sync --frozen --all-extras --python $python\` could not install the resolved set on this platform."
    echo
    details_of "$out/sync.log" "uv sync output" 40
  } >>"$md"
  finish install-failed
fi
installed=$(uv run --frozen --no-sync python -V 2>/dev/null || echo "Python $python")

# Phase 1: the suite as CI runs it (from a clean last-failed record, which phase 2 keys on).
rm -f .pytest_cache/v/cache/lastfailed
if "${pytest_cmd[@]}" -n auto >"$out/run1.log" 2>&1; then
  echo "All tests pass ($installed)." >>"$md"
  status=pass
else
  # Phase 2: again, to drop flakes. Narrow to the recorded failures (serially) when
  # pytest got far enough to record any; a collection/usage error leaves none.
  if grep -qs '::' .pytest_cache/v/cache/lastfailed; then
    rerun=("${pytest_cmd[@]}" --lf --last-failed-no-failures none -p no:xdist)
    rerun_desc="a serial re-run of just the failing tests"
  else
    rerun=("${pytest_cmd[@]}" -n auto)
    rerun_desc="a full re-run"
  fi
  if "${rerun[@]}" >"$out/run2.log" 2>&1; then
    {
      echo "Passed on $rerun_desc ($installed); the first attempt failed as below (treated as flaky, not reported):"
      echo
      echo '```text'
      summary_of "$out/run1.log"
      echo '```'
    } >>"$md"
    status=flaky
  else
    # Phase 3: same again with the deprecation family demoted, to tell "broken" from "deprecated".
    if "${rerun[@]}" "${demote[@]}" >"$out/run3.log" 2>&1; then
      {
        echo "**Deprecation warnings only** ($installed) — the failures below persist on $rerun_desc but disappear once"
        echo "\`DeprecationWarning\`/\`PendingDeprecationWarning\`/\`FutureWarning\` are not errors, so the newest versions still work and are announcing a removal we need to get ahead of."
      } >>"$md"
      status=warnings-only
    else
      echo "**Hard failures** ($installed) — the failures below persist on $rerun_desc and with deprecation warnings demoted:" >>"$md"
      status=error
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
  # Typing-only drift (e.g. a dependency tightening a signature) never fails the cell; it is context for the reader.
  if PYRIGHT_PYTHON_IGNORE_WARNINGS=1 uv run --frozen --no-sync pyright src/mcp >"$out/pyright.log" 2>&1; then
    printf '\npyright on `src/mcp` against these versions: clean (informational).\n' >>"$md"
  else
    count=$(grep -Eo '^[0-9]+ errors?' "$out/pyright.log" | tail -n1)
    {
      echo
      details_of "$out/pyright.log" "pyright on <code>src/mcp</code> against these versions: ${count:-did not complete} (informational, never filed on its own)" 30
    } >>"$md"
  fi
fi

finish "$status"
