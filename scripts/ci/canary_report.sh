#!/usr/bin/env bash
# Dependency-canary reporter: folds the resolve + per-cell artifacts into one
# Markdown report, then keeps a single tracking issue in sync with it (open on
# red, refresh while red, close on green). Driven by .github/workflows/dependency-canary.yml.
#
# Inputs (env):
#   CANARY_ARTIFACTS        directory holding canary-resolve/ and canary-cell-*/ artifacts
#   CANARY_RESOLVE_RESULT   result of the resolve job (success|failure|cancelled|skipped)
#   CANARY_FILE_ISSUES      "true" to create/update/close the tracking issue; anything else = report only
#   CANARY_LABEL            label that identifies the tracking issue (created if missing)
#   CANARY_ASSIGNEES        comma-separated logins assigned when an issue is opened
#   CANARY_RUN_URL          link to this workflow run
#   GH_TOKEN, GITHUB_REPOSITORY, GITHUB_STEP_SUMMARY (standard)

set -euo pipefail

artifacts="${CANARY_ARTIFACTS:?}"
resolve_dir="$artifacts/canary-resolve"
label="${CANARY_LABEL:?}"
run_url="${CANARY_RUN_URL:?}"
today=$(date -u +%Y-%m-%d)
body=canary-body.md

read_or() { if [ -s "$1" ]; then cat "$1"; else printf '%s' "$2"; fi; }

# ---- classify -------------------------------------------------------------

cells=() statuses=()
for f in "$artifacts"/canary-cell-*/status; do
  [ -f "$f" ] || continue
  cells+=("$(basename "$(dirname "$f")" | sed 's/^canary-cell-//')")
  statuses+=("$(tr -d '[:space:]' <"$f")")
done

count() {
  local n=0 s
  for s in "${statuses[@]}"; do if [ "$s" = "$1" ]; then n=$((n + 1)); fi; done
  echo "$n"
}
n_cells=${#statuses[@]}
n_error=$(count error)
n_install=$(count install-failed)
n_warn=$(count warnings-only)

if [ "${CANARY_RESOLVE_RESULT:-}" != "success" ]; then
  overall=unresolvable
elif [ "$n_cells" -eq 0 ]; then
  overall=no-results
elif [ "$n_error" -gt 0 ]; then
  overall=error
elif [ "$n_install" -gt 0 ]; then
  overall=install-failed
elif [ "$n_warn" -gt 0 ]; then
  overall=warnings-only
else
  overall=green
fi
# P0 only when every cell hard-fails: a fresh `pip install mcp` is broken everywhere today.
p0=false
if [ "$n_cells" -gt 0 ] && [ $((n_error + n_install)) -eq "$n_cells" ]; then p0=true; fi

suspects=$(read_or "$resolve_dir/suspects-since-green.txt" "")
[ -n "$suspects" ] || suspects=$(read_or "$resolve_dir/suspects-vs-lock.txt" "")
[ -n "$suspects" ] || suspects="see run"
cutoff=$(read_or "$resolve_dir/cutoff.txt" "unknown")
baseline=$(read_or "$resolve_dir/baseline.txt" "")
uv_version=$(read_or "$resolve_dir/uv-version.txt" "unknown")

case "$overall" in
  error) title="Newest dependency versions fail the test suite: $suspects" ;;
  install-failed) title="Newest dependency versions fail to install: $suspects" ;;
  warnings-only) title="Newest dependency versions raise deprecation warnings: $suspects" ;;
  unresolvable) title="Newest dependency versions cannot be resolved together" ;;
  no-results) title="Dependency canary produced no test results" ;;
  green) title="Newest dependency versions pass" ;;
esac

# ---- report body ---------------------------------------------------------

{
  echo "<!-- dependency-canary: this body is regenerated on every run while the issue is open -->"
  case "$overall" in
    green) echo "**Status: passing** as of $today." ;;
    error) echo "**Status: failing** — hard test failures on $n_error/$n_cells cells as of $today." ;;
    install-failed) echo "**Status: failing** — the resolved set does not install on $n_install/$n_cells cells as of $today." ;;
    warnings-only) echo "**Status: deprecations** — tests fail only because new deprecation warnings are errors under our pytest config ($n_warn/$n_cells cells) as of $today. Nothing is broken for users yet." ;;
    unresolvable) echo "**Status: unresolvable** — uv could not resolve mcp's runtime dependencies to their newest allowed versions as of $today." ;;
    no-results) echo "**Status: unknown** — the resolve step succeeded but no test cell reported (infrastructure problem; see the run)." ;;
  esac
  echo
  echo "[Workflow run]($run_url) · newest versions published before \`$cutoff\` (releases younger than a day are skipped) · uv \`$uv_version\`"
  echo
  echo "This is the weekly dependency canary: it re-resolves the runtime dependencies of \`mcp[cli,rich]\` (direct and transitive) to the newest versions our specifiers allow, ignoring \`uv.lock\`, keeps test tooling at the locked versions, and runs the test suite. PR CI never does this, so this issue is the only signal that a new upstream release breaks the SDK for users installing it today."
  echo

  if [ "$overall" = "unresolvable" ]; then
    echo "### Resolution failure"
    echo
    if [ -s "$resolve_dir/lock.log" ]; then
      echo '```text'
      tail -n 60 "$resolve_dir/lock.log"
      echo '```'
    else
      echo "The resolve job produced no log; see the workflow run."
    fi
    echo
  fi

  echo "### What changed since the last green run"
  echo
  if [ -z "$baseline" ]; then
    echo "No earlier successful scheduled run to compare against yet — use the full diff against \`uv.lock\` below."
  elif [ -s "$resolve_dir/since-green.md" ]; then
    echo "Compared with the versions that were newest at the last green run (cutoff \`$baseline\`). **Start here** — the culprit is almost always in this table."
    echo
    cat "$resolve_dir/since-green.md"
  else
    echo "Nothing in the runtime closure changed since the last green run (cutoff \`$baseline\`). If tests fail anyway, a change on \`main\` since then is the likely cause — compare with the \`locked\` leg of PR CI."
  fi
  echo

  if [ "$n_cells" -gt 0 ]; then
    echo "### Results"
    echo
    for i in "${!cells[@]}"; do echo "- \`${cells[$i]}\`: **${statuses[$i]}**"; done
    echo
    for f in "$artifacts"/canary-cell-*/cell.md; do
      if [ -f "$f" ]; then
        cat "$f"
        echo
      fi
    done
  fi

  if [ -s "$resolve_dir/held-back.md" ]; then
    echo "### Not tested at their newest release"
    echo
    echo "Something else in the resolution caps these runtime dependencies below their latest version, so this run says nothing about the versions listed as latest:"
    echo
    cat "$resolve_dir/held-back.md"
    echo
  fi

  if [ -s "$resolve_dir/vs-lock.md" ]; then
    n_diff=$(($(wc -l <"$resolve_dir/vs-lock.md") - 2))
    echo "<details><summary>All differences from the committed <code>uv.lock</code> ($n_diff packages)</summary>"
    echo
    cat "$resolve_dir/vs-lock.md"
    echo
    echo "</details>"
    echo
  fi

  echo "### Reproduce locally"
  echo
  echo "Either download the \`canary-resolve\` artifact from the run and drop its \`uv.lock\` over yours, or re-resolve the same way (same uv version, same cutoff):"
  echo
  echo '```bash'
  echo "uv self version   # the canary used $uv_version"
  if [ -s "$resolve_dir/closure.txt" ]; then
    printf 'uv lock --exclude-newer %s' "$cutoff"
    while read -r pkg; do if [ -n "$pkg" ]; then printf ' -P %s' "$pkg"; fi; done <"$resolve_dir/closure.txt"
    echo
  fi
  echo "uv sync --frozen --all-extras --python 3.14   # or the failing cell's Python"
  echo "uv run --frozen --no-sync pytest              # plus the failing test ids above"
  echo '```'
  echo
  echo "To confirm a suspect, put just that package back and re-run: \`uv lock -P '<name>==<previous version>'\`, then sync and test again."
  echo
  echo "### What to do"
  echo
  echo "1. **Deprecation warnings only** → not urgent for users; migrate off the deprecated API (supporting both old and new versions) before the removal lands. No ceiling."
  echo "2. **Hard failures / install failures** → users running \`pip install mcp\` today get this combination. Prefer a fix that supports both the old and new version of the dependency, and release it."
  echo "3. Only if users are broken *and* a real fix will take more than a day or two: add a temporary ceiling (\`<the breaking version\`) with a comment linking a follow-up issue to remove it, and cut a patch release the same day — a ceiling on \`main\` alone protects nobody, and even a released one is bypassed whenever something else in a user's environment requires the newer version. Never add a ceiling for a warnings-only or pre-release failure."
  echo "4. If the breakage is the dependency's bug, open an issue upstream and link it here."
  echo
  echo "This issue closes itself after the next green scheduled run. Closing it by hand is fine too; if the canary is still red next week it opens a fresh issue rather than reopening this one."
  echo
  echo "<sub>Generated by <code>.github/workflows/dependency-canary.yml</code> — adjust the workflow, not this text.</sub>"
} >"$body"

# GitHub caps issue bodies at 65536 characters; keep headroom.
if [ "$(wc -c <"$body")" -gt 60000 ]; then
  head -c 59000 "$body" >"$body.tmp"
  printf '\n\n…(report truncated; full version in the workflow run summary)\n' >>"$body.tmp"
  mv "$body.tmp" "$body"
fi

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "## $title"
    echo
    cat "$body"
  } >>"$GITHUB_STEP_SUMMARY"
fi
echo "canary: overall=$overall p0=$p0 cells=${cells[*]:-none} statuses=${statuses[*]:-none}"
echo "canary: title: $title"

# ---- tracking issue ------------------------------------------------------

if [ "${CANARY_FILE_ISSUES:-}" != "true" ]; then
  echo "canary: report-only run; not touching issues."
  exit 0
fi

repo="${GITHUB_REPOSITORY:?}"
# The label plus bot authorship is the identity of the tracking issue; the title is free to change.
bot_issues="repos/$repo/issues?labels=$label&creator=github-actions%5Bbot%5D&per_page=10"
open_issue=$(gh api "$bot_issues&state=open" --jq '[.[] | select(has("pull_request") | not)][0].number // empty')

if [ "$overall" = "green" ]; then
  if [ -n "$open_issue" ]; then
    gh issue comment "$open_issue" --repo "$repo" --body "Newest allowed dependency versions pass again as of $today ([run]($run_url)). Closing."
    gh issue close "$open_issue" --repo "$repo" --reason completed
    echo "canary: closed #$open_issue"
  else
    echo "canary: green and no open issue; nothing to do."
  fi
  exit 0
fi

if [ -n "$open_issue" ]; then
  gh issue edit "$open_issue" --repo "$repo" --title "$title" --body-file "$body"
  if [ "$p0" = "true" ]; then gh issue edit "$open_issue" --repo "$repo" --add-label P0; fi
  gh issue comment "$open_issue" --repo "$repo" --body "Still red on $today: **$overall** — $suspects ([run]($run_url)). The issue body above now shows this run."
  echo "canary: updated #$open_issue"
  exit 0
fi

gh label create "$label" --repo "$repo" --force --color FBCA04 \
  --description "Filed by the weekly newest-dependencies canary (.github/workflows/dependency-canary.yml)"
previous=$(gh api "$bot_issues&state=closed&sort=updated" --jq '[.[] | select(has("pull_request") | not)][0] | if . then "Previous incident: #\(.number) (closed \(.closed_at[:10]))." else empty end')
if [ -n "$previous" ]; then
  {
    echo "$previous"
    echo
    cat "$body"
  } >"$body.tmp"
  mv "$body.tmp" "$body"
fi
labels=(--label "$label" --label dependencies)
if [ "$p0" = "true" ]; then labels+=(--label P0); fi
assignees=()
if [ -n "${CANARY_ASSIGNEES:-}" ]; then assignees=(--assignee "$CANARY_ASSIGNEES"); fi
url=$(gh issue create --repo "$repo" --title "$title" --body-file "$body" "${labels[@]}" "${assignees[@]}")
echo "canary: opened $url"
