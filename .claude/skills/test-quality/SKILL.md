---
name: test-quality
description: Test quality bar for this repo. Read when writing, reviewing, or designing tests — covers naming, abstraction level, assertions, determinism, and the process for agent-driven test work.
---

# Test & code quality guide

What "best practice for new work" means in this repo. Each rule carries its recorded reasoning
where one exists; a rule with no stated why is a convention — follow it anyway.

## Naming & shape

- **Test names are behaviour sentences** stating the observable outcome, not the feature being
  poked: `test_elicit_form_decline_returns_no_content`, never `test_elicit_form_decline`.
- Plain top-level `test_*` functions; no `Test` classes (legacy files have them — don't copy).
- **Docstrings: 1–2 sentences of behaviour, honest about provenance** — spec-mandated,
  SDK-defined, or pinning a known gap? Say which: provenance is the triage key when the test
  later fails. A pinned-gap assertion breaking usually means a change *fixed* the gap; a
  spec-mandated assertion breaking means a regression.
- Define things in dependency order; nothing forward-references. For client↔server tests:
  handlers → server construction → client setup → act → assert — the test reads in the order
  the conversation happens.
- Inline the server (or equivalent setup) in the test, so the whole observable behaviour fits
  on one screen. Lift to a file-level fixture only when several tests in *that file* genuinely
  share it; never share across files.
- A big multi-step test is fine when the property is irreducibly multi-step (e.g. resumability).
  Split when a failure wouldn't tell you which claim broke — not for shortness. Compensate with
  a numbered "Steps:" docstring so a reader sees the choreography before the body.

## Level of abstraction

- **Drive through the highest-level public API that can observe the property.** Hand-built wire
  requests are brittle and don't prove the user-facing contract; tests that stay above the
  internals keep working when the internals change. Drop to raw HTTP only when the assertion is
  about something the high-level API *cannot* observe (status codes, headers, wire framing).
- **Scripting a peer over raw streams is a last resort**, reserved for behaviour the typed API
  cannot *produce* (malformed input, an impossible peer response). First ask what it would take
  for the public API to express it — often a small helper suffices. Every such test's docstring
  states why the public API couldn't do it.
- **In-memory / in-process first.** HTTP-, SSE-, and auth-shaped behaviour can all be driven
  through an in-process ASGI transport; threads only when necessary, subprocesses only when the
  process boundary is itself the thing under test. In-process isn't just faster — it surfaces
  bugs (a real stream leak was found this way) that subprocess indirection masks.
- **Tests read like real user code**: no aliasing shims in conftest, no walls of suppressions,
  no private imports unless that is genuinely the documented way to do the thing.
- The assertion must prove the round trip — no side-channel state. What the server saw comes
  back through the protocol, or via a closure-captured list asserted after the call. Handlers
  assert their dispatch identity first (`assert params.name == "add"`), proving the request
  that arrived is the request the test sent.

## Assertions

- **Transformations** (input → output the SDK produced) → full-object `snapshot(...)` equality,
  so an added or dropped field fails. Regenerate with `--inline-snapshot=fix` so intentional
  changes arrive as a reviewable diff; never hand-edit snapshot literals.
- **Pass-through values** (opaque tokens, `_meta`, cursors) → identity against the same
  variable you sent. A snapshot of a pass-through value only "matches" because a human checked
  two literals correspond — it proves nothing.
- **Errors** → `pytest.raises` + `.code` against the named constant; snapshot SDK-authored
  messages; never `match=` on message text. Third-party text (pydantic, jsonschema) → stable
  prefix only — never pin text that changes with a dependency upgrade — with a comment saying so.

## Determinism

- **No sleeps, ever.** A sleep guesses at timing instead of waiting on the condition, so it
  either flakes or pads the run — sleeps head the list of the older test code's failure modes.
  Coordinate with `anyio.Event` so the wait ends exactly when the condition holds (that
  discipline is why 529 e2e tests run in ~10 s). Sole exception: tests *of* time-based
  features, with a comment.
- Bound every indefinite wait with `anyio.fail_after(5)`. **5 is the standard** — widening it
  needs an articulable reason; "10 to be safe" is covering up a flake, not fixing one, and
  unexplained widenings propagate (one agent used 10 and every later one copied it).
- **Never assert wall-clock time, even with huge margins.** `elapsed < 0.9` on a ~0.01 s
  operation — a 90× margin — was still rejected in review. `fail_after` bounding a hang is the
  only timing primitive allowed.
- **Concurrency tests must prove genuine interleaving.** Without barriers the scheduler is free
  to serialize — "a" can start, finish, and return before "b" even begins — so two `start_soon`
  calls prove nothing. Gate with events so all parties are mid-flight before any proceeds, emit
  interleaved, then assert the demux.
- **Don't over-synchronize either.** When delivery ordering is guaranteed (notifications
  emitted during a request you're awaiting, over a single ordered in-memory stream), a plain
  collected list asserted after the call is correct; events are for messages not tied to an
  awaited operation. Verify the ordering guarantee actually holds for your transport first.
- Async tests use anyio, not asyncio.

## Behaviour philosophy

- **Pin current behaviour; never xfail.** A green suite asserting what actually happens is a
  regression bar for any refactor; an xfail proves nothing about it. Where current behaviour
  falls short of spec, pin the divergent output and record the gap as data — a tracking issue,
  with the docstring naming the known gap (suites with a requirements manifest record it as a
  divergence entry). Not hidden, not skipped.
- **Hollow-proof check**: before claiming a test covers a behaviour, re-read the claim and ask
  "which assertion proves *this*?" A passing test near a behaviour is not proof of it — a full
  review of the e2e suite found two such cases even under this discipline.

## Hygiene

- No new `# pragma`, `# type: ignore`, `# noqa` by default — restructure first; a suppression
  usually means a test or a type is missing. The narrow sanctioned escape hatches (and the
  audit to run before pushing) are in AGENTS.md. In tests, narrow types with `assert
  isinstance`; never `Any`/`object` when a real type exists.
- **Warnings raised during tests are findings, not noise** (the repo runs
  `filterwarnings = error`). Fix the cause; if the fix can't land in the same change, scope the
  suppression to the one fixture that needs it and track the real fix explicitly.
- Registered-but-never-invoked handler bodies are `raise NotImplementedError`, so they cannot
  silently become load-bearing.
- Comments live next to the line they explain, not in docstrings; single backticks for code
  refs; match the surrounding comment density (one-liners next to one-liners). No
  `from __future__ import annotations` (py310+ repo).
- Test work doesn't change `src/` as a side effect — the one mechanical exception is deleting a
  pragma a new test now covers. If a test can't be written without a library change, raise it
  as a finding or defer the test; don't quietly edit `src/`.

## Process (for agent-driven work)

- **Small chunks.** ≤10 tests per human-reviewed batch; when fanning out to multiple agents,
  ≤5 per agent. Review quality scales inversely with batch size: the observed shortcuts
  (over-stacked tests, a timing assertion, wrong abstraction level) all surfaced in one
  oversized 27-test batch.
- **Design → review → implement, as separate steps.** The design deliverable is not just the
  plan — it's the judgement calls (abstraction level, deferrals, contested assertions) stated
  explicitly, so the reviewer vetoes them before implementation rather than discovering them
  in the diff.
- **High-stakes areas get fresh adversarial reviewers** on both the design and the
  implementation — fresh, because whoever designed it (or saw the proposed fix) anchors on the
  same layer. SERIOUS findings (wrong assertion, missed MUST/SHOULD, an unrecorded known gap)
  re-loop; style doesn't. Reserve the full panel for areas where being wrong is worse than
  being slow.
- **Investigations pair a full-context look with a fresh agent given only the problem** —
  never the proposed fix — and compare conclusions. The unbiased read regularly catches
  anchoring on the wrong layer.
- **When review questions a decision, reconsider genuinely**: re-derive the tradeoff, state the
  options, recommend with reasons. Defending the original choice is a valid outcome;
  reflexively agreeing with every challenge is as bad as ignoring it.
- **Validate the reference artifact before building on it.** Whatever you treat as ground truth
  (a spec import, a baseline, a generated list), check it *first* — discovering it was
  incomplete after five batches costs far more than before batch one.
- **Verify as you go**: per-file `uv run --frozen pytest <file> -q` + pyright + ruff while
  iterating; full suite, coverage, and `./scripts/test` (when `src/` was touched) at
  integration.
- **Every agent writes notes**: what it did, what broke, and — most importantly — what it
  couldn't decide, so open questions surface instead of being silently resolved by whoever hit
  them.
- **Quality over speed is a stated goal, not a preference** ("rushing something out the door is
  not the goal here, explicitly so"). Don't quietly de-scope agreed work mid-stream;
  renegotiate scope explicitly.
- **Don't copy patterns from existing test code by default** — much of the repo's older test
  code is below the current bar (sleeps, mocks, `Test` classes, raciness). These rules define
  the bar for new work.
