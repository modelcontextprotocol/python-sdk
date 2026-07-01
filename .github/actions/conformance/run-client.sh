#!/bin/bash
# Run a client conformance suite, re-verifying unexpected failures solo.
# Concurrent suite runs on a 2-vCPU runner can push scenarios with real-time
# waits past tolerance; solo, a real failure fails again while a contention
# artifact passes. Failures that only reproduce under concurrency are excused.
set -uo pipefail

: "${CONFORMANCE_PKG:?set CONFORMANCE_PKG (pinned in .github/workflows/conformance.yml)}"
# One attempt: a solo failure on the quiet runner disproves the contention
# hypothesis; a second try would be the blind retry this script avoids.
SOLO_ATTEMPTS="${CONFORMANCE_SOLO_ATTEMPTS:-1}"

# Relative args resolve from the repo root; same contract as run-server.sh.
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

# If the harness's summary wording changes, the list comes up empty and the
# original exit code passes through - never a false green.
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
# Here-string, not a pipe: grep -q quitting early would SIGPIPE printf and,
# under pipefail, skip this guard exactly when the pattern is present.
if grep -q '^Stale baseline entries' <<<"$plain"; then
    echo "Suite also reported stale baseline entries; not retrying." >&2
    exit "$rc"
fi

# Drop the suite-only flags: --scenario replaces --suite, and solo runs are
# judged directly rather than against the baseline.
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
