#!/bin/bash
# Run a client conformance suite, re-verifying unexpected failures solo.
#
# Suite mode launches every scenario's client subprocess concurrently; on a
# 2-vCPU runner that contention can push scenarios with real-time waits (the
# SSE reconnect timing in sse-retry) past their tolerances. So a scenario the
# suite run flags as an unexpected failure is re-run alone on the then-quiet
# runner: a real failure fails again and the job stays red; a contention
# artifact passes and the job goes green, with a FLAKE_RESCUED marker written
# into the --output-dir so the artifact upload preserves the evidence.
# Failures that only reproduce under concurrency are deliberately traded
# away - the suite asserts spec compliance, not behavior under parallel load.
set -uo pipefail

: "${CONFORMANCE_PKG:?set CONFORMANCE_PKG (pinned in .github/workflows/conformance.yml)}"
SOLO_ATTEMPTS="${CONFORMANCE_SOLO_ATTEMPTS:-2}"

# Relative paths in the arguments (the client command, --output-dir) resolve
# from the repo root, same contract as run-server.sh.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../../.." || exit 1

log="$(mktemp)"
trap 'rm -f "$log"' EXIT

npx --yes "$CONFORMANCE_PKG" client "$@" 2>&1 | tee "$log"
rc=${PIPESTATUS[0]}
if [ "$rc" -eq 0 ]; then
    exit 0
fi

plain="$(sed 's/\x1b\[[0-9;]*m//g' "$log")"

# Scenarios listed under "Unexpected failures (not in baseline):". Anything
# else behind the nonzero exit (stale baseline entries, harness or infra
# errors) is not retried. The extraction is coupled to the pinned harness's
# summary wording and print order; if a pin bump changes either, the list
# comes up empty and the original failure passes through - never a false
# green.
mapfile -t scenarios < <(
    printf '%s\n' "$plain" |
        sed -n '/^Unexpected failures (not in baseline):$/,/^$/p' |
        sed -n 's/^  ✗ //p'
)
if [ "${#scenarios[@]}" -eq 0 ]; then
    exit "$rc"
fi
for scenario in "${scenarios[@]}"; do
    if ! [[ "$scenario" =~ ^[A-Za-z0-9/_-]+$ ]]; then
        echo "Extracted unexpected-failure name '${scenario}' does not look like a scenario name; passing the suite failure through." >&2
        exit "$rc"
    fi
done

# A stale baseline entry is a configuration error a solo rerun cannot excuse.
if printf '%s\n' "$plain" | grep -q '^Stale baseline entries'; then
    echo "Suite also reported stale baseline entries; not retrying." >&2
    exit "$rc"
fi

# Reuse the suite invocation's arguments for the solo runs, minus the flags
# that only make sense for a suite (--scenario replaces --suite; single runs
# are judged directly, not against the baseline). Solo results are saved next
# to the suite's so the uploaded artifact carries both.
rerun_args=()
output_dir=""
skip_next=0
expect_output_dir=0
for arg in "$@"; do
    if [ "$skip_next" -eq 1 ]; then
        if [ "$expect_output_dir" -eq 1 ]; then
            output_dir="$arg"
        fi
        skip_next=0
        expect_output_dir=0
        continue
    fi
    case "$arg" in
    --output-dir)
        skip_next=1
        expect_output_dir=1
        ;;
    --suite | --expected-failures) skip_next=1 ;;
    --output-dir=*) output_dir="${arg#--output-dir=}" ;;
    --suite=* | --expected-failures=*) ;;
    *) rerun_args+=("$arg") ;;
    esac
done
if [ -n "$output_dir" ]; then
    rerun_args+=(--output-dir "${output_dir}-solo")
fi

for scenario in "${scenarios[@]}"; do
    passed=0
    for attempt in $(seq 1 "$SOLO_ATTEMPTS"); do
        echo ""
        echo "Re-running '${scenario}' solo (attempt ${attempt}/${SOLO_ATTEMPTS})..."
        if npx --yes "$CONFORMANCE_PKG" client --scenario "$scenario" "${rerun_args[@]}"; then
            passed=1
            break
        fi
    done
    if [ "$passed" -ne 1 ]; then
        echo "'${scenario}' still fails when run alone: real failure, not suite contention." >&2
        exit 1
    fi
done

if [ -n "$output_dir" ]; then
    mkdir -p "$output_dir"
    printf '%s\n' "${scenarios[@]}" > "$output_dir/FLAKE_RESCUED"
fi
echo "All ${#scenarios[@]} unexpected failure(s) passed when re-run solo; the suite failures were parallel-run contention."
exit 0
