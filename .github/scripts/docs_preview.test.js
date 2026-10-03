// Scenario tests for docs_preview.js: who gets a preview build (`authorize`)
// and what the pull request shows afterwards (`comment`).
//
//   node --test .github/scripts/docs_preview.test.js
//
// No dependencies; the GitHub client is a small fake defined at the bottom.
// CI runs it in the checks job (.github/workflows/shared.yml).
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { authorize, comment } = require('./docs_preview.js');

const REPO = { owner: 'modelcontextprotocol', repo: 'python-sdk' };
const BASE_REPO = { id: 1, full_name: 'modelcontextprotocol/python-sdk' };
const HEAD = 'e4dfda7baa127ab00ebcd1d5324560cbe3cdfe42';
const MARKER = '<!-- docs-preview -->';

// `permission` / `role_name` as the collaborators API reports them.
const PEOPLE = {
  admin: { permission: 'admin', role_name: 'admin' },
  maintainer: { permission: 'write', role_name: 'maintain' },
  writer: { permission: 'write', role_name: 'write' },
  outsider: { permission: 'read', role_name: 'read' },
};

// ── authorize ──────────────────────────────────────────────────────────────
// `expect` is the full set of job outputs the step writes.

const authorizeScenarios = [
  {
    name: 'admin pushes to (or opens) a PR → automatic preview of that head',
    event: pushed(7, 'admin'),
    expect: { authorized: 'true', pr_number: '7', head_sha: HEAD, slash_attempt: 'false' },
  },
  {
    name: 'someone with write but not admin pushes → no automatic preview',
    event: pushed(7, 'writer'),
    expect: { authorized: 'false', pr_number: '7', head_sha: HEAD, slash_attempt: 'false' },
  },
  {
    // actions/checkout refuses a fork's head under pull_request_target, so
    // the run stops here instead of failing in `build`; /preview-docs still works.
    name: 'admin pushes to or reopens a fork PR → no automatic preview',
    event: pushed(7, 'admin', { fork: 'someone/python-sdk' }),
    expect: { authorized: 'false', pr_number: '7', head_sha: HEAD, slash_attempt: 'false' },
    permissionLookups: 0,
  },
  {
    name: 'fork PR whose fork has since been deleted → no automatic preview',
    event: pushed(7, 'admin', { fork: null }),
    expect: { authorized: 'false', pr_number: '7', head_sha: HEAD, slash_attempt: 'false' },
    permissionLookups: 0,
  },
  {
    name: 'maintainer comments /preview-docs on a fork PR → previewed like any other',
    pr: { fork: 'someone/python-sdk' },
    event: slash(7, 'maintainer'),
    expect: { authorized: 'true', pr_number: '7', head_sha: HEAD, slash_attempt: 'true' },
  },
  {
    name: 'maintainer comments /preview-docs on an open PR → preview of its current head',
    event: slash(7, 'maintainer'),
    expect: { authorized: 'true', pr_number: '7', head_sha: HEAD, slash_attempt: 'true' },
  },
  {
    name: 'admin comments /preview-docs → authorized as well',
    event: slash(7, 'admin'),
    expect: { authorized: 'true', pr_number: '7', head_sha: HEAD, slash_attempt: 'true' },
  },
  {
    name: 'writer without the maintain role comments /preview-docs → refused, recorded as an attempt',
    event: slash(7, 'writer'),
    expect: { authorized: 'false', pr_number: '7', head_sha: '', slash_attempt: 'true' },
  },
  {
    name: 'outsider comments /preview-docs → refused, recorded as an attempt',
    event: slash(7, 'outsider'),
    expect: { authorized: 'false', pr_number: '7', head_sha: '', slash_attempt: 'true' },
  },
  {
    name: '/preview-docs on a closed PR → refused even for a maintainer',
    pr: { state: 'closed' },
    event: slash(7, 'maintainer'),
    expect: { authorized: 'false', pr_number: '7', head_sha: '', slash_attempt: 'true' },
  },
];

for (const s of authorizeScenarios) {
  test(`authorize: ${s.name}`, async () => {
    const world = makeWorld({ pr: { number: 7, ...s.pr } });
    assert.deepEqual(await runAuthorize(world, s.event), s.expect);
    assert.equal(world.writes.length, 0);
    if (s.permissionLookups !== undefined) assert.equal(world.permissionLookups, s.permissionLookups);
  });
}

test('authorize: a failing permission lookup fails the step instead of deciding either way', async () => {
  const world = makeWorld({ pr: { number: 7 } });
  world.failPermissionLookup = true;
  await assert.rejects(runAuthorize(world, pushed(7, 'admin')), /boom/);
});

// ── comment ────────────────────────────────────────────────────────────────

const DEPLOYED = {
  AUTHORIZED: 'true',
  PR_NUMBER: '7',
  HEAD_SHA: HEAD,
  DEPLOY_RESULT: 'success',
  DEPLOYMENT_URL: 'https://1a2b3c.mcp-python-sdk-docs.pages.dev',
  ALIAS_URL: 'https://pr-7.mcp-python-sdk-docs.pages.dev',
  RUN_URL: 'https://github.com/modelcontextprotocol/python-sdk/actions/runs/1',
};

test('comment: a refused /preview-docs gets a plain reply to the commenter, not a preview comment', async () => {
  const world = makeWorld({ pr: { number: 7 } });
  await runComment(world, { ...DEPLOYED, AUTHORIZED: 'false', HEAD_SHA: '', DEPLOY_RESULT: 'skipped' }, 'outsider');
  assert.equal(world.comments.length, 1);
  assert.match(world.comments[0].body, /^@outsider — only repository admins or maintainers can run `\/preview-docs`/);
  assert.ok(!world.comments[0].body.includes(MARKER));
});

test('comment: first successful deploy posts one preview comment linking the alias URL and the commit', async () => {
  const world = makeWorld({ pr: { number: 7 } });
  await runComment(world, DEPLOYED, 'admin');
  assert.equal(world.comments.length, 1);
  const body = world.comments[0].body;
  assert.ok(body.startsWith(`${MARKER}\n### 📚 Documentation preview`));
  assert.match(body, /\| \*\*Preview\*\* \| https:\/\/pr-7\.mcp-python-sdk-docs\.pages\.dev \|/);
  assert.match(body, /\| \*\*Deployment\*\* \| https:\/\/1a2b3c\.mcp-python-sdk-docs\.pages\.dev \|/);
  assert.match(body, /\| \*\*Commit\*\* \| `e4dfda7` \|/);
  assert.match(body, /\| \*\*Triggered by\*\* \| @admin \|/);
  assert.deepEqual(world.writes, ['comment on #7']);
});

test('comment: a later deploy edits the existing preview comment instead of adding another', async () => {
  const world = makeWorld({ pr: { number: 7 }, comments: [{ user: 'someone', body: 'LGTM' }, { user: 'github-actions[bot]', body: `${MARKER}\nold table` }] });
  await runComment(world, { ...DEPLOYED, HEAD_SHA: 'f'.repeat(40) }, 'admin');
  assert.equal(world.comments.length, 2);
  assert.match(world.comments[1].body, /\| \*\*Commit\*\* \| `fffffff` \|/);
  assert.deepEqual(world.writes, ['edit comment 101']);
});

test("comment: someone else's comment that happens to contain the marker is left alone", async () => {
  const world = makeWorld({ pr: { number: 7 }, comments: [{ user: 'someone', body: `quoting ${MARKER} here` }] });
  await runComment(world, DEPLOYED, 'admin');
  assert.equal(world.comments.length, 2);
  assert.equal(world.comments[0].body, `quoting ${MARKER} here`);
  assert.deepEqual(world.writes, ['comment on #7']);
});

test('comment: with no alias URL the preview link falls back to the deployment URL', async () => {
  const world = makeWorld({ pr: { number: 7 } });
  await runComment(world, { ...DEPLOYED, ALIAS_URL: '' }, 'admin');
  assert.match(world.comments[0].body, /\| \*\*Preview\*\* \| https:\/\/1a2b3c\.mcp-python-sdk-docs\.pages\.dev \|/);
});

test('comment: a build or deploy that did not succeed is reported with the short SHA and a link to the run', async () => {
  const world = makeWorld({ pr: { number: 7 }, comments: [{ user: 'github-actions[bot]', body: `${MARKER}\nold table` }] });
  await runComment(world, { ...DEPLOYED, DEPLOY_RESULT: 'skipped', DEPLOYMENT_URL: '', ALIAS_URL: '' }, 'admin');
  assert.equal(world.comments.length, 1);
  assert.equal(
    world.comments[0].body,
    `${MARKER}\n### 📚 Documentation preview\n\n❌ Preview build **failed** for \`e4dfda7\` — [workflow logs](${DEPLOYED.RUN_URL}).`
  );
});

// ── Harness ────────────────────────────────────────────────────────────────

// `fork`: full name of the fork the head lives on; null for a deleted fork; omitted for a same-repo branch.
function pushed(number, sender, { fork } = {}) {
  const repo = fork === undefined ? BASE_REPO : fork === null ? null : { id: 2, full_name: fork };
  return { eventName: 'pull_request_target', actor: sender, payload: { action: 'synchronize', repository: BASE_REPO, pull_request: { number, head: { sha: HEAD, repo } }, sender: { login: sender } } };
}
function slash(number, commenter) {
  return { eventName: 'issue_comment', actor: commenter, payload: { action: 'created', issue: { number, pull_request: {} }, comment: { body: '/preview-docs', user: { login: commenter } } } };
}

async function runAuthorize(world, event) {
  const outputs = {};
  const core = { info: () => {}, setOutput: (k, v) => { outputs[k] = v; } };
  await authorize({ github: world.github, context: { repo: REPO, ...event }, core });
  return outputs;
}

async function runComment(world, env, actor) {
  const saved = {};
  for (const [k, v] of Object.entries(env)) { saved[k] = process.env[k]; process.env[k] = v; }
  try {
    await comment({ github: world.github, context: { repo: REPO, actor }, core: {} });
  } finally {
    for (const [k, v] of Object.entries(saved)) { if (v === undefined) delete process.env[k]; else process.env[k] = v; }
  }
}

// ── A tiny in-memory GitHub ────────────────────────────────────────────────

function makeWorld({ pr, comments = [] }) {
  const world = { pr: { state: 'open', ...pr }, comments: [], writes: [], failPermissionLookup: false, permissionLookups: 0, nextCommentId: 100 };
  for (const c of comments) world.comments.push({ id: world.nextCommentId++, ...c });

  const err = (status, message = 'fake error') => Object.assign(new Error(message), { status });
  const write = (what) => world.writes.push(what);
  const checkPr = (n) => { if (n !== world.pr.number) throw err(404); };

  const rest = {
    repos: {
      getCollaboratorPermissionLevel: async ({ username }) => {
        world.permissionLookups++;
        if (world.failPermissionLookup) throw err(500, 'boom');
        const person = PEOPLE[username];
        if (!person) throw err(404, 'not a user');
        return { data: { ...person, user: { login: username } } };
      },
    },
    pulls: {
      get: async ({ pull_number }) => {
        checkPr(pull_number);
        const repo = world.pr.fork ? { id: 2, full_name: world.pr.fork } : BASE_REPO;
        return { data: { number: pull_number, state: world.pr.state, head: { sha: HEAD, repo } } };
      },
    },
    issues: {
      listComments: async ({ issue_number }) => { checkPr(issue_number); return { data: world.comments.map((c) => ({ id: c.id, body: c.body, user: { login: c.user } })) }; },
      createComment: async ({ issue_number, body }) => {
        checkPr(issue_number);
        write(`comment on #${issue_number}`);
        world.comments.push({ id: world.nextCommentId++, user: 'github-actions[bot]', body });
      },
      updateComment: async ({ comment_id, body }) => {
        write(`edit comment ${comment_id}`);
        const c = world.comments.find((x) => x.id === comment_id);
        if (!c) throw err(404);
        c.body = body;
      },
    },
  };
  world.github = { rest, paginate: async (fn, args) => (await fn(args)).data };
  return world;
}
