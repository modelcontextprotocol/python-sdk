// PR intake gate. The policy lives in CONTRIBUTING.md ("How pull requests get
// in"); .github/workflows/require-linked-issue.yml wires this up to events.
//
// A pull request from someone without triage rights stays open only if its
// description links (Fixes/Closes/Resolves #N) an open issue in this repo that
// is either assigned to the PR author or labeled `help wanted`. Otherwise the
// gate labels it `missing-issue-link`, leaves one comment, and closes it. It
// re-evaluates — and reopens — the PR when the description is edited or the
// author is assigned to the issue. A triage+ user reopening the PR, removing
// the label, or adding `bypass-issue-check` overrides it, and the override
// sticks.
//
// Everything that writes goes through mutate(); when the workflow passes
// ENFORCE=false (its kill switch) the run only logs what it would have done.
'use strict';

const LABEL = 'missing-issue-link'; // marks PRs the gate has closed
const BYPASS_LABEL = 'bypass-issue-check'; // sticky maintainer override
const OPEN_LABEL = 'help wanted'; // issue label that waives assignment
const MARKER = '<!-- require-linked-issue -->';
const BOT_LOGIN = 'github-actions[bot]';
const MAX_ISSUES = 5;

module.exports = async function run({ github, context, core }) {
  const { owner, repo } = context.repo;
  const enforce = process.env.ENFORCE === 'true';
  const contributingUrl = `https://github.com/${owner}/${repo}/blob/main/CONTRIBUTING.md#how-pull-requests-get-in`;

  // ── Entry points ─────────────────────────────────────────────────────────

  if (context.eventName === 'issues') {
    // Someone was assigned an issue: re-evaluate their gate-closed PRs that
    // reference it (they may pass now).
    const issueNumber = context.payload.issue.number;
    const assignee = context.payload.assignee.login;
    const closed = await github.paginate(github.rest.issues.listForRepo, {
      owner, repo, state: 'closed', creator: assignee, labels: LABEL, per_page: 100,
    });
    const prs = closed.filter((i) => i.pull_request && closingRefs(i.body).includes(issueNumber));
    console.log(`#${issueNumber} assigned to ${assignee}: ${prs.length} gate-closed PR(s) reference it`);
    // Evaluate each independently so one transient failure doesn't strand
    // the rest (this event won't fire again for the same assignment).
    const failures = [];
    for (const pr of prs) {
      try {
        await evaluate(pr.number, 'assigned', context.payload.sender?.login, issueNumber);
      } catch (e) {
        failures.push(`#${pr.number}: ${e.message}`);
      }
    }
    if (failures.length) throw new Error(`Could not re-evaluate ${failures.join('; ')}`);
    return;
  }

  if (context.eventName === 'workflow_dispatch') {
    const n = parseInt(process.env.PR_NUMBER_INPUT, 10);
    if (!Number.isInteger(n) || n <= 0) throw new Error(`Bad pr_number input: ${process.env.PR_NUMBER_INPUT}`);
    await evaluate(n, 'dispatch', context.payload.sender?.login);
    return;
  }

  await evaluate(context.payload.pull_request.number, context.payload.action, context.payload.sender?.login);

  // ── The rules ────────────────────────────────────────────────────────────

  async function evaluate(prNumber, action, sender, hintIssue = null) {
    // Always read the PR live; the event payload can be stale by the time a
    // queued run starts.
    const { data: pr } = await github.rest.pulls.get({ owner, repo, pull_number: prNumber });
    const labels = pr.labels.map((l) => l.name);
    // An `unlabeled` run only fires for LABEL (see the workflow `if:`), so the
    // event itself proves the label was there a moment ago.
    const gated = action === 'unlabeled' || labels.includes(LABEL);
    console.log(`PR #${prNumber} by ${pr.user.login} (${pr.state}${pr.draft ? ', draft' : ''}) — ${action} by ${sender ?? '-'}, enforce=${enforce}`);

    // 0. Scope: open PRs, plus closed PRs the gate closed itself. Merged PRs
    //    and PRs someone closed for other reasons are left alone.
    if (pr.merged_at) return log('merged — nothing to do');
    if (pr.state === 'closed' && !gated) return log('closed by someone else — not ours');

    // 1. Exempt authors: bots, anyone with triage or better, and drafts (which
    //    are checked again on ready_for_review).
    if (pr.user.type === 'Bot') return log('author is a bot — exempt');
    if (await isTrusted(pr.user.login)) return pass('author has triage+ on this repo');
    if (pr.draft) return log('draft — skipped until ready for review');

    // 2. Overrides: a triage+ user reopening the PR or removing the label wants
    //    it open. Anyone else doing so just triggers a re-check.
    if ((action === 'reopened' || action === 'unlabeled') && sender && (await isTrusted(sender))) {
      return pass(`${sender} ${action === 'reopened' ? 'reopened it' : 'removed the label'} — override`, { sticky: true });
    }
    if (labels.includes(BYPASS_LABEL)) return pass(`carries ${BYPASS_LABEL}`);

    // 3. The rule: the description links an open issue in this repo that is
    //    labeled `help wanted` or assigned to the author. Only the first few
    //    references are fetched; a just-assigned issue is checked first.
    const author = pr.user.login.toLowerCase();
    const refs = closingRefs(pr.body);
    if (hintIssue && refs.includes(hintIssue)) refs.unshift(...refs.splice(refs.indexOf(hintIssue), 1));
    const linked = [];
    for (const num of refs.slice(0, MAX_ISSUES)) {
      const issue = await getIssue(num);
      if (!issue) continue; // missing, a PR, closed, or transferred away
      linked.push(num);
      if (issue.labels.some((l) => l.name.toLowerCase() === OPEN_LABEL)) return pass(`#${num} is labeled "${OPEN_LABEL}"`);
      if (issue.assignees.some((a) => a.login.toLowerCase() === author)) return pass(`author is assigned to #${num}`);
    }
    return fail(linked);

    // ── Outcomes ─────────────────────────────────────────────────────────

    async function pass(reason, { sticky = false } = {}) {
      console.log(`PASS: ${reason}`);
      if (sticky) await addLabel(prNumber, BYPASS_LABEL);
      if (pr.state === 'closed' && !(await reopen(pr, reason))) return;
      if (gated) {
        await removeLabel(prNumber, LABEL);
        await deleteGateComment(prNumber);
      }
    }

    async function fail(linkedIssues) {
      console.log(`FAIL: ${linkedIssues.length ? `not assigned to ${linkedIssues.map((n) => `#${n}`).join(', ')}` : 'no usable issue link'}`);
      await addLabel(prNumber, LABEL);
      await upsertGateComment(prNumber, closedComment(linkedIssues));
      if (pr.state === 'open') {
        await mutate(`close PR #${prNumber}`, () => github.rest.pulls.update({ owner, repo, pull_number: prNumber, state: 'closed' }));
      }
    }

    function log(msg) {
      console.log(msg);
    }
  }

  // ── Comment text ─────────────────────────────────────────────────────────

  function closedComment(linkedIssues) {
    const issues = linkedIssues.map((n) => `#${n}`).join(', ');
    const why = linkedIssues.length
      ? `you aren't currently assigned to ${issues}`
      : "its description doesn't yet link an open issue in this repository (with `Fixes #123` or similar)";
    const next = linkedIssues.length
      ? `If a maintainer would like this change as a PR from you, they'll assign you to ${issues} and this PR will reopen automatically — there's nothing more you need to do. (If you opened the issue, this PR already shows up on its timeline.)`
      : `If there isn't an issue for this yet, please [open one](https://github.com/${owner}/${repo}/issues/new/choose) — a clear description of the problem is genuinely the most useful thing for us. Then add \`Fixes #<number>\` to this PR's description. If a maintainer would like the change as a PR from you, they'll assign you to the issue and this PR will reopen automatically.`;
    return [
      MARKER,
      `Thanks for the contribution. This repository only keeps pull requests open when they're linked to an issue that a maintainer has assigned to the author — [CONTRIBUTING.md](${contributingUrl}) explains why and how we work. This PR has been closed for now because ${why}.`,
      '',
      next,
      '',
      "There's no need to open a new PR — this one will be reopened. While it's closed, please push any updates as new commits rather than force-pushing, since GitHub can't reopen a PR whose branch has been rewritten.",
      '',
      `*Maintainers: reopening this PR, removing the \`${LABEL}\` label, or adding \`${BYPASS_LABEL}\` bypasses the check.*`,
    ].join('\n');
  }

  function cannotReopenComment(pr, reason) {
    return [
      MARKER,
      `This PR now passes the intake check (${reason}), but GitHub won't let it be reopened — usually because the branch was force-pushed or deleted while the PR was closed, or because another open PR uses the same branch.`,
      '',
      `If you have another open PR from this branch, please continue there. Otherwise, either push the branch back to \`${pr.head.sha.slice(0, 7)}\` and edit this PR's description to retry, or open a new PR that links the same issue (if a maintainer had waved this one through, mention that so they can do the same there).`,
    ].join('\n');
  }

  // ── Helpers ──────────────────────────────────────────────────────────────

  async function mutate(description, fn) {
    if (!enforce) {
      console.log(`[dry-run] would ${description}`);
      return undefined;
    }
    return fn();
  }

  // Triage-or-better on this repo, from the permission endpoint's capability
  // flags (role names can be custom; author_association hides private org
  // members). Only a nonexistent user 404s; any other error must throw rather
  // than be read as "untrusted", or a maintainer's PR could be closed.
  async function isTrusted(username) {
    try {
      const { data } = await github.rest.repos.getCollaboratorPermissionLevel({ owner, repo, username });
      const p = data.user?.permissions;
      if (!p) throw new Error(`permission response for ${username} has no capability flags`);
      const trusted = Boolean(p.triage || p.push || p.maintain || p.admin);
      console.log(`  ${username}: ${trusted ? 'trusted' : 'not trusted'} (role ${data.role_name || '-'})`);
      return trusted;
    } catch (e) {
      if (e.status === 404) return false;
      throw new Error(`Permission check failed for ${username} (HTTP ${e.status ?? '?'}): ${e.message}`);
    }
  }

  // Issue numbers referenced with a closing keyword, in the forms GitHub itself
  // honors: `Fixes #1`, `closes owner/repo#1`, `Resolved https://github.com/owner/repo/issues/1`.
  function closingRefs(body) {
    const repoRef = `${owner}/${repo}`.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp(
      `\\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\\s*:?\\s*(?:${repoRef}#|#|https?://github\\.com/${repoRef}/issues/)(\\d+)`,
      'gi',
    );
    return [...new Set([...(body || '').matchAll(re)].map((m) => parseInt(m[1], 10)))];
  }

  // The linked issue, or null if it doesn't exist, is actually a PR, isn't
  // open, or has been transferred to another repository.
  async function getIssue(num) {
    let issue;
    try {
      ({ data: issue } = await github.rest.issues.get({ owner, repo, issue_number: num }));
    } catch (e) {
      if (e.status === 404 || e.status === 410) return null;
      throw new Error(`Cannot fetch issue #${num} (HTTP ${e.status ?? '?'}): ${e.message}`);
    }
    if (issue.pull_request || issue.state !== 'open') return null;
    if (!issue.repository_url?.endsWith(`/${owner}/${repo}`)) return null;
    return issue;
  }

  // Reopen a gate-closed PR. GitHub refuses (422) if the branch was rewritten
  // or deleted while closed, or another open PR uses it. Explain that in the
  // comment and make sure the control label is (still) on, so the PR stays
  // gate-managed and a later edit or override retries the reopen.
  async function reopen(pr, reason) {
    try {
      await mutate(`reopen PR #${pr.number}`, () => github.rest.pulls.update({ owner, repo, pull_number: pr.number, state: 'open' }));
      return true;
    } catch (e) {
      if (e.status !== 422) throw e;
      core.warning(`GitHub refused to reopen PR #${pr.number}: ${e.message}`);
      await addLabel(pr.number, LABEL);
      await upsertGateComment(pr.number, cannotReopenComment(pr, reason));
      return false;
    }
  }

  async function addLabel(prNumber, name) {
    await mutate(`add "${name}" to PR #${prNumber}`, async () => {
      await ensureLabelExists(name);
      await github.rest.issues.addLabels({ owner, repo, issue_number: prNumber, labels: [name] });
    });
  }

  async function removeLabel(prNumber, name) {
    await mutate(`remove "${name}" from PR #${prNumber}`, async () => {
      try {
        await github.rest.issues.removeLabel({ owner, repo, issue_number: prNumber, name });
      } catch (e) {
        if (e.status !== 404) throw e;
      }
    });
  }

  async function ensureLabelExists(name) {
    const meta = {
      [LABEL]: ['b76e79', 'Auto-closed: PR needs a linked issue assigned to its author (see CONTRIBUTING.md)'],
      [BYPASS_LABEL]: ['0e8a16', 'Maintainer override for the linked-issue intake gate'],
    }[name];
    try {
      await github.rest.issues.getLabel({ owner, repo, name });
    } catch (e) {
      if (e.status !== 404) throw e;
      try {
        await github.rest.issues.createLabel({ owner, repo, name, color: meta[0], description: meta[1] });
      } catch (createErr) {
        if (createErr.status !== 422) throw createErr; // created concurrently
      }
    }
  }

  // The gate keeps at most one comment per PR: authored by the Actions bot and
  // carrying MARKER. It's created or updated on failure and deleted on pass.
  async function findGateComment(prNumber) {
    const comments = await github.paginate(github.rest.issues.listComments, { owner, repo, issue_number: prNumber, per_page: 100 });
    return comments.find((c) => c.user?.login === BOT_LOGIN && c.body?.includes(MARKER));
  }

  async function upsertGateComment(prNumber, body) {
    const existing = await findGateComment(prNumber);
    if (!existing) {
      await mutate(`comment on PR #${prNumber}`, () => github.rest.issues.createComment({ owner, repo, issue_number: prNumber, body }));
    } else if (existing.body !== body) {
      await mutate(`update the gate comment on PR #${prNumber}`, () => github.rest.issues.updateComment({ owner, repo, comment_id: existing.id, body }));
    }
  }

  async function deleteGateComment(prNumber) {
    const existing = await findGateComment(prNumber);
    if (!existing) return;
    await mutate(`delete the gate comment on PR #${prNumber}`, async () => {
      try {
        await github.rest.issues.deleteComment({ owner, repo, comment_id: existing.id });
      } catch (e) {
        if (e.status !== 404) throw e; // already deleted by a concurrent run
      }
    });
  }
};
