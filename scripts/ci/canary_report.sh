#!/usr/bin/env bash
# Dependency-canary reporter: folds the resolve + per-cell artifacts into one
# Markdown report, then keeps a single tracking issue in sync with it (open on
# red, refresh while red, close on green). Driven by .github/workflows/dependency-canary.yml.
#
# Inputs (env):
#   CANARY_ARTIFACTS        directory holding canary-resolve/ and canary-cell-<cell>/ (merged artifacts)
#   CANARY_CELLS            JSON list of the matrix cells that were supposed to run ({"cell": ...} objects)
#   CANARY_RESOLVE_RESULT   result of the resolve job (success|failure|cancelled|skipped)
#   CANARY_TEST_RESULT      result of the test job as a whole
#   CANARY_FILE_ISSUES      "true" to create/update/close the tracking issue; anything else = report only
#   CANARY_LABEL            label that identifies the tracking issue (created if missing)
#   CANARY_ASSIGNEES        comma-separated logins assigned when an issue is opened
#   CANARY_RUN_URL          link to this workflow run
#   GH_TOKEN, GITHUB_REPOSITORY, GITHUB_STEP_SUMMARY (standard)
#
# Classification, in order:
#   resolve job not successful -> resolve-failed if `uv lock` itself failed, else infra
#   otherwise per expected cell -> its status file, or "missing" if it never reported
#     any error            -> error            (users are broken today)
#     any install-failed   -> install-failed
#     any warnings-only    -> warnings-only    (a deprecation, nothing broken yet)
#     any missing          -> infra            (the canary, not the deps, had a problem)
#     else                 -> green
# Only green closes the issue; infra never rewrites an open incident (comment only);
# P0 is added when every expected cell is error/install-failed and never removed here.

set -euo pipefail

artifacts="${CANARY_ARTIFACTS:?}"
resolve_dir="$artifacts/canary-resolve"
label="${CANARY_LABEL:?}"
run_url="${CANARY_RUN_URL:?}"
today=$(date -u +%Y-%m-%d)
body=canary-body.md

read_or() { if [ -s "$1" ]; then cat "$1"; else printf '%s' "$2"; fi; }

# ---- classify -------------------------------------------------------------

mapfile -t cells < <(jq -r '.[].cell' <<<"${CANARY_CELLS:?}")
statuses=()
for cell in "${cells[@]}"; do
  f="$artifacts/canary-cell-$cell/status"
  s=""
  if [ -f "$f" ]; then s=$(tr -d '[:space:]' <"$f"); fi
  case "$s" in
    pass | flaky | warnings-only | error | install-failed) ;;
    *) s=missing ;; # never reported, or died part-way ("incomplete")
  esac
  statuses+=("$s")
done

count() {
  local n=0 s
  for s in "${statuses[@]}"; do if [ "$s" = "$1" ]; then n=$((n + 1)); fi; done
  echo "$n"
}
n_cells=${#cells[@]}
n_error=$(count error)
n_install=$(count install-failed)
n_warn=$(count warnings-only)
n_missing=$(count missing)

resolve_result="${CANARY_RESOLVE_RESULT:-unknown}"
test_result="${CANARY_TEST_RESULT:-unknown}"
if [ "$resolve_result" != "success" ]; then
  if [ "$(read_or "$resolve_dir/lock-status" "")" = "failed" ]; then overall=resolve-failed; else overall=infra; fi
elif [ "$n_error" -gt 0 ]; then
  overall=error
elif [ "$n_install" -gt 0 ]; then
  overall=install-failed
elif [ "$n_warn" -gt 0 ]; then
  overall=warnings-only
elif [ "$n_missing" -gt 0 ] || [ "$test_result" != "success" ]; then
  overall=infra
else
  overall=green
fi
p0=false
if [ "$n_cells" -gt 0 ] && [ $((n_error + n_install)) -eq "$n_cells" ]; then p0=true; fi

cutoff=$(read_or "$resolve_dir/cutoff.txt" "unknown")
baseline=$(read_or "$resolve_dir/baseline.txt" "")
uv_version=$(read_or "$resolve_dir/uv-version.txt" "")
uv_version=${uv_version%% *}
if [ -e "$resolve_dir/suspects-since-green.txt" ]; then
  suspects=$(tr -d '\n' <"$resolve_dir/suspects-since-green.txt")
  [ -n "$suspects" ] || suspects="no dependency changed since the last green run"
else
  suspects=$(read_or "$resolve_dir/suspects-vs-lock.txt" "see run" | tr -d '\n')
fi

case "$overall" in
  error) title="Newest dependency versions fail the test suite: $suspects" ;;
  install-failed) title="Newest dependency versions fail to install: $suspects" ;;
  warnings-only) title="Newest dependency versions raise deprecation warnings: $suspects" ;;
  resolve-failed) title="Newest dependency versions could not be resolved" ;;
  infra) title="Dependency canary could not run to completion" ;;
  green) title="Newest dependency versions pass" ;;
esac
title=${title:0:200}

# ---- report body ---------------------------------------------------------

{
  echo "<!-- dependency-canary: this body is regenerated on every run while the issue is open -->"
  case "$overall" in
    green) echo "**Status: passing** as of $today." ;;
    error) echo "**Status: failing** — hard test failures on $n_error/$n_cells cells as of $today." ;;
    install-failed) echo "**Status: failing** — the resolved set does not install on $n_install/$n_cells cells as of $today." ;;
    warnings-only) echo "**Status: deprecations** — tests fail only because new deprecation warnings are errors under our pytest config ($n_warn/$n_cells cells) as of $today. Nothing is broken for users yet." ;;
    resolve-failed) echo "**Status: unresolvable** — \`uv lock\` could not produce a resolution with mcp's runtime dependencies at their newest allowed versions as of $today (log below; if it shows a network or index error rather than a conflict, this was infrastructure)." ;;
    infra) echo "**Status: incomplete** — the canary itself did not run cleanly as of $today (resolve job: $resolve_result, test job: $test_result, cells without a result: $n_missing/$n_cells). This says nothing about the dependencies; see the run." ;;
  esac
  echo
  echo "[Workflow run]($run_url) · newest versions published before \`$cutoff\` (releases younger than a day are skipped) · uv \`${uv_version:-unknown}\`"
  echo
  echo "This is the weekly dependency canary: it re-resolves the runtime dependencies of \`mcp[cli,rich]\` (direct and transitive) to the newest versions our specifiers allow, ignoring \`uv.lock\`, and runs the test suite against them. Everything else keeps its locked version unless a floated dependency forces it to move (tagged *tooling* below). PR CI never does this, so this issue is the only signal that a new upstream release breaks the SDK for people installing it today."
  echo

  if [ "$overall" = "resolve-failed" ]; then
    echo "### Resolution failure"
    echo
    echo '```text'
    read_or "$resolve_dir/lock.log" "(no lock.log in the artifact; see the run)" | tail -n 60 | cut -c1-240
    echo '```'
    echo
  fi

  if [ "$resolve_result" = "success" ]; then
    echo "### What changed since the last green run"
    echo
    if [ -z "$baseline" ]; then
      echo "No earlier successful scheduled run to compare against (none yet, or its artifact expired) — use the full diff against \`uv.lock\` below."
    elif [ -s "$resolve_dir/since-green.md" ]; then
      echo "Compared with what the last green run resolved ($baseline). **Start here** — the culprit is almost always in this table."
      echo
      cat "$resolve_dir/since-green.md"
    else
      echo "Nothing in the runtime closure changed since the last green run ($baseline). If tests fail anyway, a change on \`main\` since then is the likely cause — compare with the \`locked\` leg of PR CI."
    fi
    echo
  fi

  if [ "$n_cells" -gt 0 ] && [ "$resolve_result" = "success" ]; then
    echo "### Results"
    echo
    for i in "${!cells[@]}"; do
      case "${statuses[$i]}" in
        missing) echo "- \`${cells[$i]}\`: **no result** (timed out, cancelled, or lost before reporting; see the run)" ;;
        *) echo "- \`${cells[$i]}\`: **${statuses[$i]}**" ;;
      esac
    done
    echo
    for cell in "${cells[@]}"; do
      f="$artifacts/canary-cell-$cell/cell.md"
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
    head -n 150 "$resolve_dir/vs-lock.md"
    echo
    echo "</details>"
    echo
  fi

  echo "### Reproduce locally"
  echo
  echo "Either download the \`canary-resolve\` artifact from the run and copy its \`canary-resolve/uv.lock\` over yours, or redo the resolution exactly as the canary did (dependency groups it does not install are dropped first; the pinned uv gives identical resolver behaviour):"
  echo
  echo '```bash'
  if [ -s "$resolve_dir/strip.sh" ]; then cat "$resolve_dir/strip.sh"; fi
  if [ -s "$resolve_dir/lock-cmd.sh" ]; then
    sed "s/^uv lock/uvx uv@${uv_version:-latest} lock/" "$resolve_dir/lock-cmd.sh"
  else
    echo "# (the resolve job did not get as far as recording its uv lock command; see the run)"
  fi
  echo "uv sync --frozen --all-extras --python 3.14   # or the failing cell's Python"
  echo "uv run --frozen --no-sync pytest              # plus the failing test ids above"
  echo "git checkout -- pyproject.toml uv.lock        # undo the group strip and the relock when done"
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
  echo "This issue closes itself after the next green scheduled run. Closing it by hand is fine too; if the canary is still red next week it opens a fresh issue rather than reopening this one. \`P0\` is added automatically only when every cell hard-fails, and never removed automatically."
  echo
  echo "<sub>Generated by <code>.github/workflows/dependency-canary.yml</code> — adjust the workflow, not this text.</sub>"
} >"$body"

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "## $title"
    echo
    cat "$body"
  } >>"$GITHUB_STEP_SUMMARY"
fi
# Issue bodies cap at 65536 characters. Cells bound their own sections, so this is a
# safety net; if it ever fires, the step summary above still has everything.
if [ "$(wc -c <"$body")" -gt 60000 ]; then
  head -c 59000 "$body" >"$body.tmp"
  printf '\n```\n\n…(truncated — the complete report is in the workflow run summary: %s)\n' "$run_url" >>"$body.tmp"
  mv "$body.tmp" "$body"
fi
echo "canary: overall=$overall p0=$p0 resolve=$resolve_result test=$test_result cells=${cells[*]:-none} statuses=${statuses[*]:-none}"
echo "canary: title: $title"

# ---- tracking issue ------------------------------------------------------

if [ "${CANARY_FILE_ISSUES:-}" != "true" ]; then
  echo "canary: report-only run; not touching issues."
  exit 0
fi

repo="${GITHUB_REPOSITORY:?}"
# The label plus bot authorship is the identity of the tracking issue; the title is free to change.
bot_issues="repos/$repo/issues?labels=$label&creator=github-actions%5Bbot%5D&per_page=20"
open_issue=$(gh api "$bot_issues&state=open" --jq '[.[] | select(has("pull_request") | not)][0].number // empty')

case "$overall" in
  green)
    if [ -n "$open_issue" ]; then
      gh issue comment "$open_issue" --repo "$repo" --body "Newest allowed dependency versions pass again as of $today ([run]($run_url)). Closing."
      gh issue close "$open_issue" --repo "$repo" --reason completed
      echo "canary: closed #$open_issue"
    else
      echo "canary: green and no open issue; nothing to do."
    fi
    exit 0
    ;;
  infra)
    # Never let a broken canary rewrite (or close) a live incident; just say so.
    if [ -n "$open_issue" ]; then
      gh issue comment "$open_issue" --repo "$repo" --body "The canary could not run to completion on $today (resolve: $resolve_result, test: $test_result, cells without a result: $n_missing/$n_cells) — [run]($run_url). Leaving this issue as it was."
      echo "canary: infra week; commented on #$open_issue"
      exit 0
    fi
    ;;
esac

# Most recent earlier incident, for context (issues list newest-created first).
previous=$(gh api "$bot_issues&state=closed" --jq '[.[] | select(has("pull_request") | not)][0] | if . then "Previous incident: #\(.number) (closed \(.closed_at[:10]))." else empty end')
if [ -n "$previous" ]; then
  {
    echo "$previous"
    echo
    cat "$body"
  } >"$body.tmp"
  mv "$body.tmp" "$body"
fi

if [ -n "$open_issue" ]; then
  gh issue edit "$open_issue" --repo "$repo" --title "$title" --body-file "$body"
  if [ "$p0" = "true" ]; then gh issue edit "$open_issue" --repo "$repo" --add-label P0; fi
  gh issue comment "$open_issue" --repo "$repo" --body "Still red on $today: **$overall** — $suspects ([run]($run_url)). The issue body above now shows this run."
  echo "canary: updated #$open_issue"
  exit 0
fi

# Create the label on first use; an existing (possibly customised) one is left alone.
gh label create "$label" --repo "$repo" --color FBCA04 \
  --description "Filed by the weekly newest-dependencies canary (.github/workflows/dependency-canary.yml)" 2>/dev/null || true
labels=(--label "$label")
if [ "$overall" != "infra" ]; then labels+=(--label dependencies); fi
if [ "$p0" = "true" ]; then labels+=(--label P0); fi
assignees=()
if [ -n "${CANARY_ASSIGNEES:-}" ]; then assignees=(--assignee "$CANARY_ASSIGNEES"); fi
url=$(gh issue create --repo "$repo" --title "$title" --body-file "$body" "${labels[@]}" "${assignees[@]}")
echo "canary: opened $url"
