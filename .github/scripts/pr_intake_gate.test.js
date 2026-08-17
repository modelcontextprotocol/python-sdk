// Scenario tests for pr_intake_gate.js. Each case sets up a tiny in-memory
// repository (pull requests, issues, people), fires one event at the gate, and
// checks what the gate left behind: PR state, labels, and its comment.
//
//   node --test .github/scripts/pr_intake_gate.test.js
//
// No dependencies; the GitHub client is a small fake defined at the bottom.
// CI runs it in the checks job (.github/workflows/shared.yml).
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const gate = require('./pr_intake_gate.js');

const LABEL = 'missing-issue-link';
const BYPASS = 'bypass-issue-check';
const REPO = { owner: 'modelcontextprotocol', repo: 'python-sdk' };

// People. Only the capability flags matter to the gate.
const PEOPLE = {
  maintainer: { type: 'User', perms: { admin: true, maintain: true, push: true, triage: true, pull: true } },
  triager: { type: 'User', perms: { triage: true, pull: true } }, // e.g. a trusted-contributors team
  outsider: { type: 'User', perms: { pull: true } },
  'dependabot[bot]': { type: 'Bot', perms: {} },
  'somebot[bot]': { type: 'Bot', perms: {} },
};

// ── Scenarios ──────────────────────────────────────────────────────────────
// `prs` / `issues` describe the world before the event; `expect` describes each
// PR afterwards: state, labels, and comment ('closed' = the "this PR has been
// closed" comment, 'cannot-reopen' = the refused-reopen comment, null = none).
// `writes: 0` additionally asserts the gate touched nothing at all.

const scenarios = [
  {
    name: 'outsider opens a PR with no issue link → labeled, commented, closed',
    prs: [pr(3300, 'outsider')],
    event: opened(3300, 'outsider'),
    expect: { 3300: { state: 'closed', labels: [LABEL], comment: 'closed' } },
  },
  {
    name: 'outsider links an open issue reported by someone else, not assigned → closed',
    prs: [pr(3300, 'outsider', { body: 'Fixes #10' })],
    issues: [issue(10)],
    event: opened(3300, 'outsider'),
    expect: { 3300: { state: 'closed', labels: [LABEL], comment: 'closed' } },
  },
  {
    name: 'outsider links an issue they are assigned to → stays open, untouched',
    prs: [pr(3300, 'outsider', { body: 'closes #10' })],
    issues: [issue(10, { assignees: ['outsider'] })],
    event: opened(3300, 'outsider'),
    expect: { 3300: { state: 'open', labels: [], comment: null } },
    writes: 0,
  },
  {
    name: 'outsider links a `help wanted` issue → stays open without assignment',
    prs: [pr(3300, 'outsider', { body: 'Resolves modelcontextprotocol/python-sdk#10' })],
    issues: [issue(10, { labels: ['help wanted'] })],
    event: opened(3300, 'outsider'),
    expect: { 3300: { state: 'open', labels: [], comment: null } },
    writes: 0,
  },
  {
    name: 'links only count when they use a closing keyword and point at an open issue here',
    prs: [pr(3300, 'outsider', { body: 'Related to #10, fixes owner/other#10, prefixes #10, Fixes #11, Fixes #12' })],
    issues: [
      issue(10, { assignees: ['outsider'] }), // referenced, but never with a closing keyword for this repo
      issue(11, { assignees: ['outsider'], state: 'closed' }), // closed issues don't count
      issue(12, { assignees: ['outsider'], repository_url: 'https://api.github.com/repos/modelcontextprotocol/typescript-sdk' }), // transferred away
    ],
    event: opened(3300, 'outsider'),
    expect: { 3300: { state: 'closed', labels: [LABEL], comment: 'closed' } },
  },
  {
    name: 'gate-closed PR: author edits the description to link a qualifying issue → reopened, label and comment removed',
    prs: [pr(3300, 'outsider', { state: 'closed', labels: [LABEL], body: 'Fixes #10', gateComment: true })],
    issues: [issue(10, { labels: ['help wanted'] })],
    event: edited(3300, 'outsider'),
    expect: { 3300: { state: 'open', labels: [], comment: null } },
  },
  {
    name: 'gate-closed PR: maintainer assigns the author on the linked issue → reopened',
    prs: [
      pr(3300, 'outsider', { state: 'closed', labels: [LABEL], body: 'Fixes #10', gateComment: true }),
      pr(3301, 'outsider', { state: 'closed', labels: [LABEL], body: 'Fixes #99', gateComment: true }), // different issue: untouched
    ],
    issues: [issue(10, { assignees: ['outsider'] }), issue(99)],
    event: assigned(10, 'outsider', 'maintainer'),
    expect: {
      3300: { state: 'open', labels: [], comment: null },
      3301: { state: 'closed', labels: [LABEL], comment: 'closed' },
    },
  },
  {
    name: 'gate-closed PR: maintainer reopens it → stays open with the sticky bypass label',
    prs: [pr(3300, 'outsider', { state: 'open', labels: [LABEL], gateComment: true })], // payload arrives post-reopen
    event: reopened(3300, 'maintainer'),
    expect: { 3300: { state: 'open', labels: [BYPASS], comment: null } },
  },
  {
    name: 'gate-closed PR: triage-role user removes the label → reopened with the sticky bypass label',
    prs: [pr(3300, 'outsider', { state: 'closed', labels: [], gateComment: true })], // payload arrives post-unlabel
    event: unlabeled(3300, 'triager'),
    expect: { 3300: { state: 'open', labels: [BYPASS], comment: null } },
  },
  {
    name: 'gate-closed PR: some other bot strips the label → re-checked, label restored, still closed',
    prs: [pr(3300, 'outsider', { state: 'closed', labels: [], gateComment: true })],
    event: unlabeled(3300, 'somebot[bot]'),
    expect: { 3300: { state: 'closed', labels: [LABEL], comment: 'closed' } },
  },
  {
    name: 'PR carrying the bypass label is never re-closed, even after edits that would fail',
    prs: [pr(3300, 'outsider', { labels: [BYPASS], body: 'no link at all' })],
    event: edited(3300, 'outsider'),
    expect: { 3300: { state: 'open', labels: [BYPASS], comment: null } },
    writes: 0,
  },
  {
    name: 'previously passing PR edited to drop its link → closed again',
    prs: [pr(3300, 'outsider', { body: 'see #10' })],
    issues: [issue(10, { assignees: ['outsider'] })],
    event: edited(3300, 'outsider'),
    expect: { 3300: { state: 'closed', labels: [LABEL], comment: 'closed' } },
  },
  {
    name: "maintainer's own PR is exempt (and reopening it adds no labels)",
    prs: [pr(3300, 'maintainer')],
    event: reopened(3300, 'maintainer'),
    expect: { 3300: { state: 'open', labels: [], comment: null } },
    writes: 0,
  },
  {
    name: 'triage-role author is exempt',
    prs: [pr(3300, 'triager')],
    event: opened(3300, 'triager'),
    expect: { 3300: { state: 'open', labels: [], comment: null } },
    writes: 0,
  },
  {
    name: 'bot-authored PR (Dependabot) is exempt',
    prs: [pr(3300, 'dependabot[bot]')],
    event: opened(3300, 'dependabot[bot]'),
    expect: { 3300: { state: 'open', labels: [], comment: null } },
    writes: 0,
  },
  {
    name: 'draft PR is skipped until it is marked ready for review',
    prs: [pr(3300, 'outsider', { draft: true })],
    event: opened(3300, 'outsider'),
    expect: { 3300: { state: 'open', labels: [], comment: null } },
    writes: 0,
  },
  {
    name: 'draft marked ready for review with no link → closed',
    prs: [pr(3300, 'outsider')],
    event: readyForReview(3300, 'outsider'),
    expect: { 3300: { state: 'closed', labels: [LABEL], comment: 'closed' } },
  },
  {
    name: 'PR a maintainer closed by hand (no gate label) is left alone when edited',
    prs: [pr(3300, 'outsider', { state: 'closed' })],
    event: edited(3300, 'outsider'),
    expect: { 3300: { state: 'closed', labels: [], comment: null } },
    writes: 0,
  },
  {
    name: 'merged PR still carrying the label is left alone',
    prs: [pr(3300, 'outsider', { state: 'closed', merged_at: '2026-08-15T00:00:00Z', labels: [LABEL] })],
    event: edited(3300, 'outsider'),
    expect: { 3300: { state: 'closed', labels: [LABEL], comment: null } },
    writes: 0,
  },
  {
    name: 'GitHub refuses to reopen (branch rewritten while closed) → stays closed, comment explains',
    prs: [pr(3300, 'outsider', { state: 'closed', labels: [LABEL], body: 'Fixes #10', gateComment: true, refuseReopen: true })],
    issues: [issue(10, { assignees: ['outsider'] })],
    event: edited(3300, 'outsider'),
    expect: { 3300: { state: 'closed', labels: [LABEL], comment: 'cannot-reopen' } },
  },
  {
    name: 'gate-closed PR: maintainer adds the bypass label → reopened, and the label sticks',
    prs: [pr(3300, 'outsider', { state: 'closed', labels: [LABEL, BYPASS], gateComment: true })], // payload arrives post-label
    event: labeled(3300, 'maintainer', BYPASS),
    expect: { 3300: { state: 'open', labels: [BYPASS], comment: null } },
  },
  {
    name: 'refused reopen after a label-removal override → both labels on, so the PR stays gate-managed',
    prs: [pr(3300, 'outsider', { state: 'closed', labels: [], gateComment: true, refuseReopen: true })],
    event: unlabeled(3300, 'triager'),
    expect: { 3300: { state: 'closed', labels: [BYPASS, LABEL], comment: 'cannot-reopen' } },
  },
  {
    name: 'after a refused reopen, once the branch is restored an edit retries and reopens',
    prs: [pr(3300, 'outsider', { state: 'closed', labels: [BYPASS, LABEL], comments: [{ user: 'github-actions[bot]', body: "<!-- require-linked-issue -->\n…GitHub won't let it be reopened…" }] })],
    event: edited(3300, 'outsider'),
    expect: { 3300: { state: 'open', labels: [BYPASS], comment: null } },
  },
  {
    name: 'assignment reopens the PR even when the assigned issue is referenced after several others',
    prs: [pr(3300, 'outsider', { state: 'closed', labels: [LABEL], body: 'Fixes #1 fixes #2 fixes #3 fixes #4 fixes #5 fixes #6', gateComment: true })],
    issues: [issue(1), issue(2), issue(3), issue(4), issue(5), issue(6, { assignees: ['outsider'] })],
    event: assigned(6, 'outsider', 'maintainer'),
    expect: { 3300: { state: 'open', labels: [], comment: null } },
  },
  {
    name: 'a comment planted by the author with the marker is ignored; the gate posts its own',
    prs: [pr(3300, 'outsider', { comments: [{ user: 'outsider', body: '<!-- require-linked-issue -->\nnice try' }] })],
    event: opened(3300, 'outsider'),
    expect: { 3300: { state: 'closed', labels: [LABEL], comment: 'closed', foreignComments: 1 } },
  },
  {
    name: 'manual dispatch evaluates an old, never-gated PR like a new one',
    prs: [pr(3150, 'outsider')],
    event: dispatch(3150, 'maintainer'),
    expect: { 3150: { state: 'closed', labels: [LABEL], comment: 'closed' } },
  },
];

for (const s of scenarios) {
  test(s.name, async () => {
    const world = makeWorld(s);
    await run(world, s.event, { enforce: true });
    assert.deepEqual(observe(world, s.expect), s.expect);
    if (s.writes !== undefined) assert.equal(world.writes.length, s.writes, `writes: ${world.writes.join(', ')}`);
  });
}

test('kill switch (ENFORCE=false) reaches the same verdicts but writes nothing', async () => {
  for (const s of scenarios) {
    const world = makeWorld(s);
    await run(world, s.event, { enforce: false });
    assert.equal(world.writes.length, 0, `${s.name}: ${world.writes.join(', ')}`);
  }
});

test('on assignment, one PR failing to re-evaluate does not stop the others (run still fails)', async () => {
  const world = makeWorld({
    prs: [
      pr(3300, 'outsider', { state: 'closed', labels: [LABEL], body: 'Fixes #10', gateComment: true }),
      pr(3301, 'outsider', { state: 'closed', labels: [LABEL], body: 'Fixes #10', gateComment: true }),
    ],
    issues: [issue(10, { assignees: ['outsider'] })],
  });
  world.failPullsGet = 3300;
  await assert.rejects(run(world, assigned(10, 'outsider', 'maintainer'), { enforce: true }), /Could not re-evaluate #3300/);
  assert.equal(world.prs.get(3301).state, 'open');
});

test('an API error while checking permissions fails the run rather than closing the PR', async () => {
  const world = makeWorld({ prs: [pr(3300, 'outsider')] });
  world.failPermissionLookup = true;
  await assert.rejects(run(world, opened(3300, 'outsider'), { enforce: true }), /Permission check failed/);
  assert.equal(world.writes.length, 0);
});

// ── Scenario helpers ───────────────────────────────────────────────────────

function pr(number, author, o = {}) {
  return { number, author, state: 'open', draft: false, body: '', labels: [], merged_at: null, comments: [], gateComment: false, refuseReopen: false, ...o };
}
function issue(number, o = {}) {
  return { number, state: 'open', labels: [], assignees: [], repository_url: `https://api.github.com/repos/${REPO.owner}/${REPO.repo}`, ...o };
}
function prEvent(action, number, sender, extra = {}) {
  return { eventName: 'pull_request_target', payload: { action, pull_request: { number }, sender: { login: sender }, ...extra } };
}
function opened(number, sender) { return prEvent('opened', number, sender); }
function edited(number, sender) { return prEvent('edited', number, sender); }
function reopened(number, sender) { return prEvent('reopened', number, sender); }
function readyForReview(number, sender) { return prEvent('ready_for_review', number, sender); }
function unlabeled(number, sender) { return prEvent('unlabeled', number, sender, { label: { name: LABEL } }); }
function labeled(number, sender, name) { return prEvent('labeled', number, sender, { label: { name } }); }
function assigned(issueNumber, assignee, sender) {
  return { eventName: 'issues', payload: { action: 'assigned', issue: { number: issueNumber }, assignee: { login: assignee }, sender: { login: sender } } };
}
function dispatch(number, sender) {
  return { eventName: 'workflow_dispatch', prNumber: number, payload: { inputs: { pr_number: String(number) }, sender: { login: sender } } };
}

async function run(world, event, { enforce }) {
  process.env.ENFORCE = enforce ? 'true' : 'false';
  process.env.PR_NUMBER_INPUT = event.prNumber ? String(event.prNumber) : '';
  const core = { warning: () => {}, setFailed: (m) => { throw new Error(`setFailed: ${m}`); } };
  const quiet = console.log;
  console.log = () => {};
  try {
    await gate({ github: world.github, context: { repo: REPO, ...event }, core });
  } finally {
    console.log = quiet;
  }
}

// What the gate left behind, in the same shape as a scenario's `expect`.
function observe(world, expect) {
  const out = {};
  for (const num of Object.keys(expect)) {
    const p = world.prs.get(Number(num));
    const gateComments = p.comments.filter((c) => c.user === 'github-actions[bot]' && c.body.includes('<!-- require-linked-issue -->'));
    assert.ok(gateComments.length <= 1, `PR #${num} has ${gateComments.length} gate comments`);
    const kind = !gateComments.length ? null : gateComments[0].body.includes("won't let it be reopened") ? 'cannot-reopen' : 'closed';
    out[num] = { state: p.state, labels: [...p.labels].sort(), comment: kind };
    if ('foreignComments' in expect[num]) out[num].foreignComments = p.comments.length - gateComments.length;
  }
  return out;
}

// ── A tiny in-memory GitHub ────────────────────────────────────────────────

function makeWorld({ prs = [], issues = [] }) {
  const world = { prs: new Map(), issues: new Map(), writes: [], failPermissionLookup: false, failPullsGet: null, nextCommentId: 100 };
  for (const p of prs) {
    const copy = structuredClone(p);
    copy.comments = copy.comments.map((c) => ({ id: world.nextCommentId++, ...c }));
    if (copy.gateComment) copy.comments.push({ id: world.nextCommentId++, user: 'github-actions[bot]', body: '<!-- require-linked-issue -->\nThanks for the contribution. …closed for now…' });
    world.prs.set(p.number, copy);
  }
  for (const i of issues) world.issues.set(i.number, structuredClone(i));

  const err = (status, message = 'fake error') => Object.assign(new Error(message), { status });
  const write = (what) => world.writes.push(what);
  const getPr = (n) => { const p = world.prs.get(n); if (!p) throw err(404); return p; };
  const apiPr = (p) => ({
    number: p.number, state: p.state, draft: p.draft, body: p.body, merged_at: p.merged_at,
    labels: p.labels.map((name) => ({ name })),
    user: { login: p.author, type: PEOPLE[p.author].type },
    head: { sha: 'abc1234def', ref: 'patch-1', repo: { name: REPO.repo, owner: { login: p.author } } },
  });

  const rest = {
    repos: {
      getCollaboratorPermissionLevel: async ({ username }) => {
        if (world.failPermissionLookup) throw err(500, 'boom');
        const person = PEOPLE[username];
        if (!person) throw err(404, 'not a user');
        return { data: { role_name: 'custom', user: { permissions: { admin: false, maintain: false, push: false, triage: false, pull: false, ...person.perms } } } };
      },
    },
    pulls: {
      get: async ({ pull_number }) => { if (world.failPullsGet === pull_number) throw err(502, 'bad gateway'); return { data: apiPr(getPr(pull_number)) }; },
      update: async ({ pull_number, state }) => {
        const p = getPr(pull_number);
        write(`${state === 'open' ? 'reopen' : 'close'} #${pull_number}`);
        if (state === 'open' && p.refuseReopen) throw err(422, 'Validation Failed: state cannot be changed');
        p.state = state;
        return { data: apiPr(p) };
      },
    },
    issues: {
      get: async ({ issue_number }) => {
        if (world.prs.has(issue_number)) return { data: { ...apiPr(getPr(issue_number)), pull_request: {} } };
        const i = world.issues.get(issue_number);
        if (!i) throw err(404);
        return { data: { ...i, labels: i.labels.map((name) => ({ name })), assignees: i.assignees.map((login) => ({ login })) } };
      },
      listForRepo: async ({ state, creator, labels }) => ({
        data: [...world.prs.values()]
          .filter((p) => p.state === state && p.author === creator && p.labels.includes(labels))
          .map((p) => ({ number: p.number, body: p.body, pull_request: {} })),
      }),
      getLabel: async () => ({ data: {} }),
      createLabel: async ({ name }) => { write(`create label ${name}`); },
      addLabels: async ({ issue_number, labels }) => {
        const p = getPr(issue_number);
        write(`label #${issue_number} ${labels}`);
        for (const l of labels) if (!p.labels.includes(l)) p.labels.push(l);
      },
      removeLabel: async ({ issue_number, name }) => {
        const p = getPr(issue_number);
        write(`unlabel #${issue_number} ${name}`);
        if (!p.labels.includes(name)) throw err(404);
        p.labels = p.labels.filter((l) => l !== name);
      },
      listComments: async ({ issue_number }) => ({ data: getPr(issue_number).comments.map((c) => ({ id: c.id, body: c.body, user: { login: c.user } })) }),
      createComment: async ({ issue_number, body }) => {
        write(`comment on #${issue_number}`);
        getPr(issue_number).comments.push({ id: world.nextCommentId++, user: 'github-actions[bot]', body });
      },
      updateComment: async ({ comment_id, body }) => {
        write(`edit comment ${comment_id}`);
        for (const p of world.prs.values()) for (const c of p.comments) if (c.id === comment_id) c.body = body;
      },
      deleteComment: async ({ comment_id }) => {
        write(`delete comment ${comment_id}`);
        for (const p of world.prs.values()) p.comments = p.comments.filter((c) => c.id !== comment_id);
      },
    },
  };
  world.github = { rest, paginate: async (fn, args) => (await fn(args)).data };
  return world;
}
